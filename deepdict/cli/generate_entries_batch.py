#!/usr/bin/env python3
"""Batched dictionary entry generation, codex (subscription) or API backend.

Each model call generates a whole batch of N words as a JSON array; the
batches run concurrently. Per-word output files give free resume (a word
whose file exists is skipped). Words that fail (batch unparseable, word
missing from the array, or entry fails schema validation) are stashed in a
failures dir for later bulk review instead of blocking the run — the design
the user chose: low error rate, don't do per-batch rollback.

Backends:
  --backend codex : shell out to `codex exec` (uses the ChatGPT/Codex
                    subscription; reasoning effort via --reasoning).
  --backend api   : OpenAI-compatible HTTP (DeepSeek by default) via ChatClient.

Usage:
  # subscription backend, 50/batch, 5 concurrent (the config used for V2)
  python3 -m deepdict.cli.generate_entries_batch \
      --words wordlists/merged.csv \
      --backend codex --batch-size 50 --workers 5 --reasoning low \
      --out-dir work/entries
"""

import argparse
import hashlib
import json
import re
import subprocess
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from ..entries import load_word_column, write_json_atomic
from ..ids import stable_id
from ..llm import ChatClient, with_retries
from ..schema import validate_entry


def build_batch_prompt(system_prompt, words):
    listing = "\n".join(f"{i + 1}. {w}" for i, w in enumerate(words))
    instr = (
        "下面是上面定义的词条编辑任务。请为这 "
        f"{len(words)} 个英文词各生成一个符合上述结构的词条 JSON object，"
        "严格遵守上述所有规则（解释面向快速阅读；名动同义则合并、按真实频率裁剪义项；"
        "pos 用单一词性）。\n\n"
        "输出一个 JSON 数组，数组每个元素是一个词条 object，顺序与下面词表一致。"
        "只输出这个 JSON 数组本身，不要任何额外文字、Markdown 或代码块。\n\n"
        "词表：\n" + listing
    )
    return system_prompt + "\n\n---\n\n" + instr


def parse_array(text):
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = raw.split("```", 2)[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    data = json.loads(raw)
    if isinstance(data, dict):
        # Some models wrap the array, e.g. {"entries": [...]}.
        lists = [v for v in data.values() if isinstance(v, list)]
        data = lists[0] if len(lists) == 1 and "word" not in data else [data]
    if not isinstance(data, list):
        raise ValueError("model output is not a JSON array")
    return data


class UnparseableOutput(ValueError):
    """The model answered, but not with the JSON array that was asked for
    (for example a refusal in prose). Carries the raw text for the record."""

    def __init__(self, text, usage):
        super().__init__("model output is not a JSON array")
        self.text = text
        self.usage = usage


def prompt_id(path):
    """Short content hash that identifies a prompt version."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:8]


def parse_reset_seconds(text):
    """Best-effort: pull a 'try again / resets in ...' duration from an error."""
    text = (text or "").lower()
    m = re.search(r"(\d+)\s*h(?:our)?s?\s*(\d+)?\s*m", text)
    if m:
        h = int(m.group(1)); mi = int(m.group(2) or 0)
        return h * 3600 + mi * 60
    m = re.search(r"(?:in|after|resets? in|try again in)\s*(\d+)\s*(second|sec|minute|min|hour|hr)", text)
    if m:
        n = int(m.group(1)); unit = m.group(2)
        mult = 1 if unit.startswith("s") else 60 if unit.startswith("m") else 3600
        return n * mult
    # absolute time, e.g. "try again at 2:42 AM"
    m = re.search(r"try again at\s*(\d{1,2}):(\d{2})\s*(am|pm)", text)
    if m:
        from datetime import datetime, timedelta
        hh = int(m.group(1)) % 12 + (12 if m.group(3) == "pm" else 0)
        mm = int(m.group(2))
        now = datetime.now()
        target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        return int((target - now).total_seconds())
    return None


# Codex features that add tool definitions or instructions to every call but
# are useless for a pure text task. Turning them off, and replacing Codex's
# own coding-agent instructions with the dictionary prompt, cuts the fixed
# per-call input by more than half.
SLIM_DISABLE = [
    "apps", "browser_use", "browser_use_external", "computer_use", "plugins",
    "view_image", "sleep_tool", "shell_tool", "image_generation",
]
USAGE_KEYS = ["input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens"]


def configured_mcp_servers():
    """Names of the MCP servers in the user's Codex config.

    Every `codex exec` starts all of them, so a run with many workers carries
    that many copies of each server for nothing: the generator uses no tools."""
    try:
        text = (Path.home() / ".codex" / "config.toml").read_text(encoding="utf-8")
    except OSError:
        return []
    names = re.findall(r'^\[mcp_servers\.("[^"]+"|[A-Za-z0-9_-]+)\]', text, re.M)
    return sorted({name.strip('"') for name in names})


MCP_SERVERS = configured_mcp_servers()


def codex_generate(prompt, reasoning, model, timeout, instructions_file=None, web_search=False):
    """Run one `codex exec` call. Returns (final message text, token usage).

    With instructions_file, the file replaces Codex's built-in instructions
    (so it acts as the system prompt) and unneeded features are disabled.
    """
    with tempfile.NamedTemporaryFile("r", suffix=".txt", delete=False) as f:
        out_path = Path(f.name)
    cmd = [
        "codex", "exec", "--ephemeral", "-s", "read-only", "--skip-git-repo-check", "--json",
        "-c", f'model_reasoning_effort="{reasoning}"',
        "-o", str(out_path),
    ]
    if instructions_file:
        cmd += ["-c", f'model_instructions_file="{Path(instructions_file).resolve()}"']
        # Without Codex's own instructions the model starts verifying words by
        # web search, which multiplies the input tokens of a call. Leave it on
        # only when asked: it is worth the cost for words newer than the model.
        if not web_search:
            cmd += ["-c", 'web_search="disabled"']
        for feature in SLIM_DISABLE:
            cmd += ["--disable", feature]
        for name in MCP_SERVERS:
            key = name if re.fullmatch(r"[A-Za-z0-9_-]+", name) else f'"{name}"'
            cmd += ["-c", f"mcp_servers.{key}.enabled=false"]
    if model:
        cmd += ["-m", model]
    cmd += ["-"]
    try:
        proc = subprocess.run(
            cmd, input=prompt, text=True, capture_output=True, timeout=timeout
        )
        usage = dict.fromkeys(USAGE_KEYS, 0)
        messages = []
        for line in proc.stdout.splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if event.get("type") == "turn.completed":
                for key in USAGE_KEYS:
                    usage[key] += int((event.get("usage") or {}).get(key) or 0)
            item = event.get("item") or {}
            if event.get("type") == "item.completed" and item.get("type") == "agent_message":
                messages.append(item.get("text") or "")
        text = out_path.read_text(encoding="utf-8") if out_path.exists() else ""
        # `-o` holds only the last message, and the model does not always put
        # the whole answer there: it may send the array and then a closing
        # remark, or send the entries as several messages. Gather the entries
        # from everything it said and keep whichever reading yields the most.
        text = max(messages + [text], key=len)
        gathered = []
        for message in messages:
            try:
                gathered += [e for e in parse_array(message) if isinstance(e, dict) and "word" in e]
            except ValueError:
                continue
        try:
            best = len(parse_array(text))
        except ValueError:
            best = 0
        if len(gathered) > best:
            text = json.dumps(gathered, ensure_ascii=False)
        if not text.strip():
            raise ValueError(f"codex returned empty output (exit {proc.returncode}): {proc.stderr[-300:]}")
        return text, usage
    finally:
        out_path.unlink(missing_ok=True)


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--words", type=Path, default=Path("wordlists/merged.csv"))
    parser.add_argument("--prompt", type=Path, default=Path("deepdict/prompts/entry-generation-system.md"))
    parser.add_argument("--out-dir", type=Path, default=Path("work/entries"))
    parser.add_argument("--failures-dir", type=Path, default=None,
                        help="Defaults to <out-dir>-failures.")
    parser.add_argument("--run-summary-dir", type=Path, default=Path("work/runs/entries"))
    parser.add_argument("--backend", choices=["codex", "api"], default="codex")
    parser.add_argument("--batch-size", type=int, default=50)
    parser.add_argument("--workers", type=int, default=5)
    parser.add_argument("--reasoning", default="high", help="codex reasoning effort (low/medium/high/max).")
    parser.add_argument("--model", default=None,
                        help="Model name. Defaults to gpt-6.2-astra for codex; the API backend uses its own default.")
    parser.add_argument("--slim", action="store_true",
                        help="codex only: use the prompt file as Codex's instructions and disable "
                             "unneeded features, which cuts the fixed input tokens of every call.")
    parser.add_argument("--web-search", action="store_true",
                        help="With --slim, let the model search the web (for words newer than the model).")
    parser.add_argument("--timeout", type=float, default=600)
    parser.add_argument("--abort-after-consecutive-batch-errors", type=int, default=3,
                        help="Circuit breaker: stop the run after this many consecutive batch-level "
                             "failures (assumed rate-limit/quota), instead of hammering the backend.")
    parser.add_argument("--limit", type=int, help="Only process the first N undone words (smoke test).")
    parser.add_argument("--overwrite", action="store_true", help="Regenerate even if output exists.")
    parser.add_argument("--api-key-env", default="DEEPSEEK_API_KEY")
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main():
    args = parse_args()
    failures_dir = args.failures_dir or Path(str(args.out_dir) + "-failures")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    failures_dir.mkdir(parents=True, exist_ok=True)
    args.run_summary_dir.mkdir(parents=True, exist_ok=True)

    all_words = load_word_column(args.words)
    if args.overwrite:
        todo = list(all_words)
    else:
        todo = [w for w in all_words if not (args.out_dir / f"{stable_id(w)}.json").exists()]
    if args.limit is not None:
        todo = todo[: args.limit]

    batches = [todo[i : i + args.batch_size] for i in range(0, len(todo), args.batch_size)]
    system_prompt = args.prompt.read_text(encoding="utf-8").strip()
    if args.backend == "codex" and not args.model:
        args.model = "gpt-6.2-astra"  # named explicitly so every entry records what wrote it
    meta = {
        "model": args.model or "deepseek-v4-pro",
        "prompt": prompt_id(args.prompt),
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    }
    if args.backend == "codex":
        meta["effort"] = args.reasoning

    print(f"backend={args.backend} reasoning={args.reasoning} batch_size={args.batch_size} workers={args.workers}")
    print(f"total_words={len(all_words)} todo={len(todo)} batches={len(batches)}")
    print(f"out_dir={args.out_dir} failures_dir={failures_dir}")

    if args.dry_run:
        for i, b in enumerate(batches[:2]):
            print(f"-- batch {i}: {len(b)} words: {b[:5]}...")
        return 0

    client = None
    if args.backend == "api":
        kwargs = {"api_key_env": args.api_key_env, "max_tokens": 8000}
        if args.base_url:
            kwargs["base_url"] = args.base_url
        if args.model:
            kwargs["model"] = args.model
        client = ChatClient.from_env(**kwargs)

    def run_batch(words):
        usage = {}
        if args.backend == "codex":
            if args.slim:
                prompt = build_batch_prompt("", words).split("---\n\n", 1)[1]
                text, usage = codex_generate(prompt, args.reasoning, args.model, args.timeout,
                                             instructions_file=args.prompt, web_search=args.web_search)
            else:
                prompt = build_batch_prompt(system_prompt, words)
                text, usage = codex_generate(prompt, args.reasoning, args.model, args.timeout)
        else:
            # api backend sends system + a thin user instruction
            def call():
                listing = "\n".join(f"{i + 1}. {w}" for i, w in enumerate(words))
                user = "请为下面词表的每个词生成词条，输出 JSON 数组：\n" + listing
                data, _ = client.chat_json(system_prompt, user)
                return json.dumps(data)
            text, _ = with_retries(call, retries=1)
        try:
            return parse_array(text), usage
        except ValueError:
            raise UnparseableOutput(text, usage)

    def generate(words):
        """Run a batch; if the answer cannot be parsed, split the batch in two
        and retry, so that one word the model will not handle does not take
        the other words down with it. Returns (entries, usage, unparseable)
        where unparseable maps a single word to the raw answer it produced."""
        try:
            entries, usage = run_batch(words)
            return entries, dict(usage), {}
        except UnparseableOutput as exc:
            if len(words) == 1:
                return [], dict(exc.usage), {words[0]: exc.text}
            mid = len(words) // 2
            entries, usage, unparseable = [], dict(exc.usage), {}
            for part in (words[:mid], words[mid:]):
                part_entries, part_usage, part_bad = generate(part)
                entries += part_entries
                unparseable.update(part_bad)
                for key, value in part_usage.items():
                    usage[key] = usage.get(key, 0) + value
            return entries, usage, unparseable

    throttled = threading.Event()
    reset_hint = {"seconds": None}

    def process_batch(words):
        result = {"ok": 0, "excluded": 0, "failed": 0, "declined": 0, "unparseable": 0,
                  "batch_error": 0, "skipped": 0, "flagged": []}
        if throttled.is_set():
            result["skipped"] = len(words)
            return result, None
        try:
            entries, usage, unparseable = generate(words)
            result["usage"] = usage
        except Exception as exc:
            # Whole-batch failure (likely rate-limit/quota/network). Do NOT stash to
            # failures — the words have no output file, so they retry on resume.
            # The orchestrator counts consecutive batch errors to trip the breaker.
            secs = parse_reset_seconds(str(exc))
            if secs:
                reset_hint["seconds"] = secs
            result["batch_error"] = len(words)
            return result, f"BATCH ERROR ({len(words)}w): {str(exc)[:90]}"

        by_word = {}
        by_letters = {}
        for e in entries:
            if isinstance(e, dict) and isinstance(e.get("word"), str):
                by_word[e["word"].lower()] = e
                by_letters.setdefault(re.sub(r"[^a-z0-9]", "", e["word"].lower()), e)

        if len(by_word) < len(words) / 2 and not unparseable:
            # Most of the batch is missing. Keep the model's answer so the cause can be found.
            note = failures_dir / f"_short-batch-{stable_id(words[0])}.json"
            write_json_atomic(note, {"words": words, "returned": len(by_word),
                                     "raw_entries": entries[:5] if isinstance(entries, list) else str(entries)[:2000]})
        for w in words:
            if w in unparseable:
                # The model answered this single word with something other than
                # an entry. Keep what it said so the case can be looked at.
                write_json_atomic(failures_dir / f"{stable_id(w)}.json",
                                  {"word": w, "reason": "unparseable_output",
                                   "raw": unparseable[w][:2000]})
                result["unparseable"] += 1
                result["flagged"].append(w)
                continue
            entry = by_word.get(w.lower())
            if entry is None:
                # The model sometimes respells the headword ("oxy genos" for
                # "oxygenos"). Same letters, same word: take it back under ours.
                entry = by_letters.get(re.sub(r"[^a-z0-9]", "", w.lower()))
                if entry is not None:
                    entry["word"] = w
            if isinstance(entry, dict) and entry.get("exclude_reason") == "model_declined":
                # The model reported that it would not write a normal entry.
                # Never let that pass as an ordinary exclusion.
                write_json_atomic(failures_dir / f"{stable_id(w)}.json",
                                  {"word": w, "reason": "model_declined",
                                   "note": str(entry.get("note", ""))[:500]})
                result["declined"] += 1
                result["flagged"].append(w)
                continue
            if entry is None:
                write_json_atomic(failures_dir / f"{stable_id(w)}.json",
                                  {"word": w, "reason": "missing_from_array"})
                result["failed"] += 1
                continue
            try:
                entry.pop("meta", None)  # provenance is ours to write, not the model's
                cleaned = validate_entry({**entry, "meta": meta}, entry.get("word", w))
            except Exception as exc:
                write_json_atomic(failures_dir / f"{stable_id(w)}.json",
                                  {"word": w, "reason": "validation_error",
                                   "error": str(exc)[:200], "raw": entry})
                result["failed"] += 1
                continue
            write_json_atomic(args.out_dir / f"{stable_id(w)}.json", cleaned)
            fail_path = failures_dir / f"{stable_id(w)}.json"
            if fail_path.exists():
                fail_path.unlink()
            result["excluded" if not cleaned["include"] else "ok"] += 1
        return result, None

    totals = {"ok": 0, "excluded": 0, "failed": 0, "declined": 0, "unparseable": 0,
              "batch_error": 0, "skipped": 0}
    flagged_words = []
    usage_total = dict.fromkeys(USAGE_KEYS, 0)
    calls = 0
    started = datetime.now(timezone.utc)
    done_batches = 0
    consecutive_errors = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(process_batch, b): b for b in batches}
        for fut in as_completed(futs):
            res, note = fut.result()
            for k in totals:
                totals[k] += res.get(k, 0)
            flagged_words += res.get("flagged", [])
            if "usage" in res:
                calls += 1
                for k in USAGE_KEYS:
                    usage_total[k] += res["usage"].get(k, 0)
            done_batches += 1
            if res["batch_error"]:
                consecutive_errors += 1
            elif res["ok"] or res["excluded"] or res["declined"] or res["unparseable"]:
                consecutive_errors = 0
            if not throttled.is_set() and consecutive_errors >= args.abort_after_consecutive_batch_errors:
                throttled.set()
                print(f"!! circuit breaker tripped after {consecutive_errors} consecutive batch errors "
                      f"— stopping run (reset_hint={reset_hint['seconds']}s)", flush=True)
            if any(res[k] for k in ("ok", "excluded", "declined", "unparseable", "batch_error")):
                msg = (f"[batch {done_batches}/{len(batches)}] "
                       f"ok={res['ok']} excl={res['excluded']} fail={res['failed']} "
                       f"declined={res['declined']} unparseable={res['unparseable']} batch_err={res['batch_error']}")
                if note:
                    msg += f" :: {note}"
                print(msg, flush=True)

    finished = datetime.now(timezone.utc)
    aborted = throttled.is_set()
    summary = {
        "started_at": started.isoformat(),
        "finished_at": finished.isoformat(),
        "duration_seconds": round((finished - started).total_seconds(), 1),
        "backend": args.backend,
        "model": args.model,
        "prompt": meta["prompt"],
        "slim": args.slim,
        "web_search": args.web_search,
        "calls": calls,
        "usage": usage_total,
        "reasoning": args.reasoning,
        "batch_size": args.batch_size,
        "workers": args.workers,
        "words_attempted": len(todo),
        "batches": len(batches),
        "totals": totals,
        "declined_or_unparseable_words": sorted(flagged_words),
        "aborted_rate_limited": aborted,
        "reset_seconds_hint": reset_hint["seconds"],
        "out_dir": str(args.out_dir),
        "failures_dir": str(failures_dir),
    }
    run_id = finished.strftime("%Y%m%dT%H%M%SZ")
    write_json_atomic(args.run_summary_dir / f"{run_id}.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if aborted:
        print(f"ABORTED_RATE_LIMITED reset_hint={reset_hint['seconds']}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
