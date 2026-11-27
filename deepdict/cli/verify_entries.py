#!/usr/bin/env python3
"""Adversarially verify risky entries with a second LLM pass.

Reads the risk-ranked CSV from deepdict.cli.qa_scan, shows each suspect entry
to a skeptical reviewer prompt together with independent evidence (the
ECDICT reference translation and the suspected lookalike neighbor, when one
exists), and records a structured verdict per word. Verdicts feed a human
review CSV; nothing is auto-deleted.

For independence, consider pointing --base-url/--model at a different
provider than the one that generated the entries: a model tends to repeat
its own hallucinations when asked to check itself.

Needs an API key. Use --dry-run to inspect prompts without spending tokens.

Usage:
  python3 -m deepdict.cli.verify_entries --tiers A --workers 16
  python3 -m deepdict.cli.verify_entries --tiers A,B --limit 2000
"""

import argparse
import csv
import json
from pathlib import Path

from ..entries import iter_entries, write_json_atomic
from ..ids import stable_id
from ..llm import ChatClient, add_usage, run_tasks, with_retries

PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "verify-system.md"

VERDICTS = {"ok", "wrong_word", "fabricated", "wrong_senses", "partly_wrong", "unsure"}


def load_risk_rows(path, tiers):
    rows = []
    with path.open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            if row.get("tier") in tiers:
                rows.append(row)
    return rows


def build_user_prompt(word, entry, ecdict_translation, lookalike):
    payload = {
        "word": word,
        "senses": entry.get("senses", []),
    }
    lines = [
        "请审查下面这个词条。",
        "",
        f"输入词：{word}",
        f"词条：{json.dumps(payload, ensure_ascii=False)}",
        f"参考释义（ECDICT）：{ecdict_translation or '（无，该词典不收录此词）'}",
    ]
    if lookalike:
        lines.append(f"疑似混淆词：{lookalike}")
    lines += ["", "只输出符合要求的 JSON object。"]
    return "\n".join(lines)


def validate_verdict(data, expected_word):
    if not isinstance(data, dict):
        raise ValueError("verdict must be a JSON object")
    extra = set(data) - {"word", "verdict", "confidence", "problems", "note_zh"}
    if extra:
        raise ValueError(f"unexpected keys: {sorted(extra)}")
    if data.get("word") != expected_word:
        raise ValueError(f"word mismatch: {data.get('word')!r}")
    verdict = data.get("verdict")
    if verdict not in VERDICTS:
        raise ValueError(f"invalid verdict: {verdict!r}")
    confidence = data.get("confidence")
    if not isinstance(confidence, int) or isinstance(confidence, bool) or not 0 <= confidence <= 10:
        raise ValueError("confidence must be an integer 0-10")
    problems = data.get("problems")
    if not isinstance(problems, list) or not all(isinstance(p, str) for p in problems):
        raise ValueError("problems must be an array of strings")
    note = data.get("note_zh", "")
    if not isinstance(note, str):
        raise ValueError("note_zh must be a string")
    return {
        "word": expected_word,
        "verdict": verdict,
        "confidence": confidence,
        "problems": [p.strip() for p in problems if p.strip()],
        "note_zh": note.strip(),
    }


def write_report(out_dir, report_path):
    rows = []
    for path in sorted(Path(out_dir).glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        rows.append(data)
    order = {"wrong_word": 0, "fabricated": 1, "wrong_senses": 2, "partly_wrong": 3, "unsure": 4, "ok": 5}
    rows.sort(key=lambda r: (order.get(r["verdict"], 9), -r["confidence"]))
    with Path(report_path).open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["word", "verdict", "confidence", "problems", "note_zh"])
        writer.writeheader()
        for row in rows:
            writer.writerow({
                "word": row["word"],
                "verdict": row["verdict"],
                "confidence": row["confidence"],
                "problems": " | ".join(row["problems"]),
                "note_zh": row["note_zh"],
            })
    print(f"report={report_path} rows={len(rows)}")


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--risk", type=Path, default=Path("work/qa/risk-ranked.csv"))
    parser.add_argument("--tiers", default="A", help="Comma-separated tiers to verify, e.g. A,B")
    parser.add_argument("--entries", type=Path, default=Path("work/entries"))
    parser.add_argument("--ecdict", type=Path, default=Path("vendor/ecdict/ecdict.csv"))
    parser.add_argument("--out", type=Path, default=Path("work/verify"))
    parser.add_argument("--error-dir", type=Path, default=Path("work/verify-errors"))
    parser.add_argument("--run-summary-dir", type=Path, default=Path("work/runs/verify"))
    parser.add_argument("--report", type=Path, default=Path("work/verify/verdicts.csv"))
    parser.add_argument("--limit", type=int)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--api-key-env", default="DEEPSEEK_API_KEY")
    parser.add_argument("--base-url", default=None, help="Override API base URL (e.g. a second provider).")
    parser.add_argument("--model", default=None)
    parser.add_argument("--temperature", type=float, default=0.1)
    parser.add_argument("--max-tokens", type=int, default=500)
    parser.add_argument("--timeout", type=float, default=60)
    parser.add_argument("--retries", type=int, default=2)
    return parser.parse_args()


def main():
    args = parse_args()
    tiers = {t.strip() for t in args.tiers.split(",") if t.strip()}
    risk_rows = load_risk_rows(args.risk, tiers)
    if args.limit is not None:
        risk_rows = risk_rows[: args.limit]
    print(f"risk_rows={len(risk_rows)} tiers={sorted(tiers)}")

    wanted = {row["word"].lower() for row in risk_rows}
    entries = {}
    for entry in iter_entries(args.entries):
        if entry.get("include") and entry["word"].lower() in wanted:
            entries[entry["word"].lower()] = entry
    print(f"entries_loaded={len(entries)}")

    system_prompt = PROMPT_PATH.read_text(encoding="utf-8").strip()

    if args.dry_run:
        for row in risk_rows[:3]:
            entry = entries.get(row["word"].lower())
            if entry is None:
                continue
            print(f"--- user prompt: {row['word']} ---")
            print(build_user_prompt(
                row["word"], entry, row.get("ecdict_translation"), row.get("lookalike")
            ))
        return 0

    client_kwargs = {
        "api_key_env": args.api_key_env,
        "temperature": args.temperature,
        "max_tokens": args.max_tokens,
        "timeout": args.timeout,
    }
    if args.base_url:
        client_kwargs["base_url"] = args.base_url
    if args.model:
        client_kwargs["model"] = args.model
    client = ChatClient.from_env(**client_kwargs)

    def process_one(row):
        word = row["word"]
        out_path = args.out / f"{stable_id(word)}.json"
        error_path = args.error_dir / f"{stable_id(word)}.json"
        if out_path.exists() and not args.overwrite:
            return "skipped", word, {}
        entry = entries.get(word.lower())
        if entry is None:
            return "missing_entry", word, {}

        usage_total = {}

        def call():
            data, usage = client.chat_json(
                system_prompt,
                build_user_prompt(word, entry, row.get("ecdict_translation"), row.get("lookalike")),
            )
            add_usage(usage_total, usage)
            return validate_verdict(data, word)

        try:
            verdict, _ = with_retries(call, retries=args.retries)
            write_json_atomic(out_path, verdict)
            if error_path.exists():
                error_path.unlink()
            return verdict["verdict"], word, usage_total
        except Exception as exc:
            write_json_atomic(error_path, {
                "word": word,
                "error_type": type(exc).__name__,
                "error": str(exc),
            })
            return "failed", word, usage_total

    from datetime import datetime, timezone

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    counts = run_tasks(
        risk_rows,
        process_one,
        workers=args.workers,
        run_summary_path=args.run_summary_dir / f"{run_id}.json",
        run_meta={
            "task": "verify",
            "tiers": sorted(tiers),
            "rows": len(risk_rows),
            "model": client.model,
        },
    )
    write_report(args.out, args.report)
    return 1 if counts.get("failed") else 0


if __name__ == "__main__":
    raise SystemExit(main())
