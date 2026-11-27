#!/usr/bin/env python3
"""Validate a batch of generated entries and render an A/B vs the v1 baseline.

Used for the backend/prompt A/B test: feed it the JSON array that codex (or
any backend) returns for the 20-word set, and it validates each entry against
the production schema, then prints a word-by-word side-by-side of the existing
DeepSeek v1 entry vs the new one — so the explanation quality difference is
visible at a glance.

Usage:
  # after capturing codex output to work/ab-test/codex-out.json
  python3 -m deepdict.cli.ab_compare --new work/ab-test/codex-out.json
"""

import argparse
import json
from pathlib import Path

from ..schema import validate_entry


def load_array(path):
    raw = Path(path).read_text(encoding="utf-8").strip()
    # tolerate accidental code fences
    if raw.startswith("```"):
        raw = raw.split("```", 2)[1]
        if raw.startswith("json"):
            raw = raw[4:]
    data = json.loads(raw)
    if isinstance(data, dict):
        data = [data]
    return data


def fmt_entry(entry):
    lines = []
    for s in entry.get("senses", []):
        cl = (s.get("context_label") or "").strip()
        head = f"[{s.get('pos','')}{'|'+cl if cl else ''}] {s.get('gloss_zh','')}"
        lines.append(head)
        df = (s.get("definition_zh") or "").strip()
        if df:
            lines.append(f"      └ {df}")
    if not entry.get("include", True):
        return f"(excluded: {entry.get('exclude_reason')})"
    return "\n".join(lines)


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--new", type=Path, required=True, help="JSON array of new entries.")
    parser.add_argument("--baseline", type=Path, default=Path("work/ab-test/v1-baseline.json"))
    parser.add_argument("--out", type=Path, default=Path("work/ab-test/comparison.md"))
    return parser.parse_args()


def main():
    args = parse_args()
    new_entries = load_array(args.new)
    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))

    by_word = {}
    errors = []
    for entry in new_entries:
        word = entry.get("word", "?")
        try:
            by_word[word] = validate_entry(entry, word)
        except Exception as exc:
            errors.append((word, str(exc)))

    md = ["# A/B comparison: DeepSeek v1 (old prompt) vs new backend (v2 prompt)", ""]
    if errors:
        md.append(f"## Schema errors: {len(errors)}")
        for w, e in errors:
            md.append(f"- `{w}`: {e}")
        md.append("")

    md.append(f"Validated new entries: {len(by_word)} / {len(new_entries)}")
    md.append("")
    for word in [e.get("word") for e in new_entries]:
        new = by_word.get(word)
        old = baseline.get(word)
        md.append(f"## {word}")
        md.append("")
        md.append("**v1 (DeepSeek, old prompt):**")
        md.append("```")
        md.append(fmt_entry(old) if old else "(not in current dictionary)")
        md.append("```")
        md.append("**new (v2 prompt):**")
        md.append("```")
        md.append(fmt_entry(new) if new else "(missing / failed validation)")
        md.append("```")
        md.append("")

    args.out.write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"validated={len(by_word)}/{len(new_entries)} errors={len(errors)}")
    print(f"comparison={args.out}")


if __name__ == "__main__":
    main()
