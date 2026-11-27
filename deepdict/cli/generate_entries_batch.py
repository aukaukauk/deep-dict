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
        data = [data]
    if not isinstance(data, list):
        raise ValueError("model output is not a JSON array")
    return data


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


def codex_generate(prompt, reasoning, model, timeout):
    with tempfile.NamedTemporaryFile("r", suffix=".txt", delete=False) as f:
        out_path = Path(f.name)
    cmd = [
        "codex", "exec", "--ephemeral", "-s", "read-only", "--skip-git-repo-check",
        "-c", f'model_reasoning_effort="{reasoning}"',
        "-o", str(out_path),
    ]
    if model:
        cmd += ["-m", model]
    cmd += ["-"]
    try:
        proc = subprocess.run(
            cmd, input=prompt, text=True, capture_output=True, timeout=timeout
        )
        text = out_path.read_text(encoding="utf-8") if out_path.exists() else ""
        if not text.strip():
            raise ValueError(f"codex returned empty output (exit {proc.returncode}): {proc.stderr[-300:]}")
        return text
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
    parser.add_argument("--reasoning", default="low", help="codex reasoning effort (low/medium/high).")
    parser.add_argument("--model", default=None, help="Override model (codex -m or API model).")
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
        prompt = build_batch_prompt(system_prompt, words)
        if args.backend == "codex":
            text = codex_generate(prompt, args.reasoning, args.model, args.timeout)
        else:
            # api backend sends system + a thin user instruction
            def call():
                listing = "\n".join(f"{i + 1}. {w}" for i, w in enumerate(words))
                user = "请为下面词表的每个词生成词条，输出 JSON 数组：\n" + listing
                data, _ = client.chat_json(system_prompt, user)
                return json.dumps(data)
            text, _ = with_retries(call, retries=1)
        return parse_array(text)

    throttled = threading.Event()
    reset_hint = {"seconds": None}

    def process_batch(words):
        result = {"ok": 0, "excluded": 0, "failed": 0, "batch_error": 0, "skipped": 0}
        if throttled.is_set():
            result["skipped"] = len(words)
            return result, None
        try:
            entries = run_batch(words)
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
        for e in entries:
            if isinstance(e, dict) and isinstance(e.get("word"), str):
                by_word[e["word"].lower()] = e

        for w in words:
            entry = by_word.get(w.lower())
            if entry is None:
                write_json_atomic(failures_dir / f"{stable_id(w)}.json",
                                  {"word": w, "reason": "missing_from_array"})
                result["failed"] += 1
                continue
            try:
                cleaned = validate_entry(entry, entry.get("word", w))
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

    totals = {"ok": 0, "excluded": 0, "failed": 0, "batch_error": 0, "skipped": 0}
    started = datetime.now(timezone.utc)
    done_batches = 0
    consecutive_errors = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(process_batch, b): b for b in batches}
        for fut in as_completed(futs):
            res, note = fut.result()
            for k in totals:
                totals[k] += res.get(k, 0)
            done_batches += 1
            if res["batch_error"]:
                consecutive_errors += 1
            elif res["ok"] or res["excluded"]:
                consecutive_errors = 0
            if not throttled.is_set() and consecutive_errors >= args.abort_after_consecutive_batch_errors:
                throttled.set()
                print(f"!! circuit breaker tripped after {consecutive_errors} consecutive batch errors "
                      f"— stopping run (reset_hint={reset_hint['seconds']}s)", flush=True)
            if res["ok"] or res["excluded"] or res["batch_error"]:
                msg = (f"[batch {done_batches}/{len(batches)}] "
                       f"ok={res['ok']} excl={res['excluded']} fail={res['failed']} batch_err={res['batch_error']}")
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
        "reasoning": args.reasoning,
        "batch_size": args.batch_size,
        "workers": args.workers,
        "words_attempted": len(todo),
        "batches": len(batches),
        "totals": totals,
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
