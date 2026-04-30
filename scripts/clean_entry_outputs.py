#!/usr/bin/env python3
import argparse
import json
import re
from collections import Counter
from pathlib import Path

from generate_entries import validate_entry, write_json_atomic


TRAILING_PAREN_RE = re.compile(r"^(.+?)（([^（）]+)）$")
PUNCTUATION = "，。；：、,.!！？?（）()《》“”\"'‘’·-— "


def normalize_text(value):
    return re.sub(r"\s+", "", value or "").strip()


def sentence(value):
    value = (value or "").strip()
    if not value:
        return ""
    if value[-1] in "。！？":
        return value
    return value + "。"


def merge_definition(existing, added):
    existing = (existing or "").strip()
    added = sentence(added)
    if not added:
        return existing
    if not existing:
        return added
    if normalize_text(added.rstrip("。")) in normalize_text(existing):
        return existing
    return added + existing


def migrate_trailing_paren(sense):
    gloss = sense.get("gloss_zh", "")
    match = TRAILING_PAREN_RE.match(gloss)
    if not match:
        return False

    base = match.group(1).strip()
    note = match.group(2).strip()
    if not base or not note:
        return False

    sense["gloss_zh"] = base
    sense["definition_zh"] = merge_definition(sense.get("definition_zh"), note)
    return True


def gloss_mostly_repeated_by_definition(gloss, definition, threshold):
    gloss_chars = [ch for ch in normalize_text(gloss) if ch not in PUNCTUATION]
    definition_chars = {ch for ch in normalize_text(definition) if ch not in PUNCTUATION}
    if not gloss_chars or not definition_chars:
        return False
    matched = sum(1 for ch in gloss_chars if ch in definition_chars)
    return matched / len(gloss_chars) >= threshold


def drop_repetitive_definition(sense, max_len, threshold):
    definition = sense.get("definition_zh", "")
    if not definition or len(definition) > max_len:
        return False
    if not gloss_mostly_repeated_by_definition(sense.get("gloss_zh", ""), definition, threshold):
        return False
    sense.pop("definition_zh", None)
    return True


def dedupe_senses(senses, mode):
    seen = set()
    cleaned = []
    removed = []

    for sense in senses:
        if mode == "exact":
            key = (
                sense.get("pos", "").strip(),
                sense.get("context_label", "").strip(),
                sense.get("gloss_zh", "").strip(),
                sense.get("definition_zh", "").strip(),
            )
        elif mode == "gloss":
            key = normalize_text(sense.get("gloss_zh", ""))
        elif mode == "plain-gloss":
            if sense.get("context_label", "").strip():
                cleaned.append(sense)
                continue
            key = normalize_text(sense.get("gloss_zh", ""))
        else:
            cleaned.append(sense)
            continue

        if key in seen:
            removed.append(sense)
            continue
        seen.add(key)
        cleaned.append(sense)

    return cleaned, removed


def clean_entry(data, args):
    cleaned = {
        "word": data["word"],
        "senses": [dict(sense) for sense in data["senses"]],
    }
    changes = Counter()
    detail = {
        "removed_duplicate_senses": [],
        "migrated_gloss_parens": [],
        "dropped_repetitive_definitions": [],
    }

    if args.dedupe in {"exact", "gloss", "plain-gloss"}:
        new_senses, removed = dedupe_senses(cleaned["senses"], args.dedupe)
        if removed:
            changes["dedupe_senses"] += len(removed)
            detail["removed_duplicate_senses"] = removed
            cleaned["senses"] = new_senses

    if args.migrate_parens:
        for idx, sense in enumerate(cleaned["senses"], 1):
            before = dict(sense)
            if migrate_trailing_paren(sense):
                changes["migrate_parens"] += 1
                detail["migrated_gloss_parens"].append({"sense": idx, "before": before, "after": dict(sense)})

    if args.drop_repetitive_defs:
        for idx, sense in enumerate(cleaned["senses"], 1):
            before = dict(sense)
            if drop_repetitive_definition(sense, args.repetitive_def_max_len, args.repetitive_def_threshold):
                changes["drop_repetitive_defs"] += 1
                detail["dropped_repetitive_definitions"].append(
                    {"sense": idx, "before": before, "after": dict(sense)}
                )

    cleaned = validate_entry(cleaned, data["word"])
    return cleaned, changes, detail


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def parse_args():
    parser = argparse.ArgumentParser(
        description="Clean generated dictionary entry JSON files without calling a model."
    )
    parser.add_argument("--input-dir", type=Path, default=Path("outputs/entries"))
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Write cleaned JSON files here. If omitted, no entry files are written.",
    )
    parser.add_argument("--report", type=Path, default=Path("outputs/cleaning-report.json"))
    parser.add_argument(
        "--dedupe",
        choices=["none", "exact", "gloss", "plain-gloss"],
        default="none",
        help=(
            "exact removes identical senses; gloss removes later senses with the same gloss_zh; "
            "plain-gloss only does that when context_label is empty."
        ),
    )
    parser.add_argument("--migrate-parens", action="store_true")
    parser.add_argument("--drop-repetitive-defs", action="store_true")
    parser.add_argument("--repetitive-def-max-len", type=int, default=25)
    parser.add_argument("--repetitive-def-threshold", type=float, default=0.7)
    parser.add_argument(
        "--changed-only",
        action="store_true",
        help="With --output-dir, write only files that changed instead of copying every entry.",
    )
    parser.add_argument(
        "--sample-limit",
        type=int,
        default=30,
        help="Maximum changed-entry details to store in the report.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    files = sorted(args.input_dir.glob("*.json"))
    summary = Counter()
    changed_entries = []
    errors = []

    for path in files:
        try:
            original = load_json(path)
            validate_entry(original, original.get("word"))
            cleaned, changes, detail = clean_entry(original, args)
        except Exception as exc:
            errors.append({"file": str(path), "error": str(exc)})
            continue

        changed = cleaned != validate_entry(original, original["word"])
        for key, value in changes.items():
            summary[key] += value
        if changed:
            summary["changed_entries"] += 1
            if len(changed_entries) < args.sample_limit:
                changed_entries.append(
                    {
                        "file": str(path),
                        "word": original["word"],
                        "changes": dict(changes),
                        "detail": detail,
                    }
                )

        if args.output_dir and (changed or not args.changed_only):
            out_path = args.output_dir / path.name
            write_json_atomic(out_path, cleaned if changed else validate_entry(original, original["word"]))

    report = {
        "input_dir": str(args.input_dir),
        "output_dir": str(args.output_dir) if args.output_dir else None,
        "files_seen": len(files),
        "files_written": len(list(args.output_dir.glob("*.json"))) if args.output_dir and args.output_dir.exists() else 0,
        "errors": errors,
        "summary": dict(summary),
        "options": {
            "dedupe": args.dedupe,
            "migrate_parens": args.migrate_parens,
            "drop_repetitive_defs": args.drop_repetitive_defs,
            "repetitive_def_max_len": args.repetitive_def_max_len,
            "repetitive_def_threshold": args.repetitive_def_threshold,
            "changed_only": args.changed_only,
        },
        "changed_entry_samples": changed_entries,
    }
    write_json_atomic(args.report, report)
    print(json.dumps(report["summary"], ensure_ascii=False, sort_keys=True))
    print(f"files_seen={report['files_seen']} files_written={report['files_written']} errors={len(errors)}")
    print(f"report={args.report}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
