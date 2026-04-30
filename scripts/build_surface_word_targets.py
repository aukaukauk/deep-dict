#!/usr/bin/env python3
import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

from filter_ecdict_main_words import SHORT_ALLOWLIST


def load_words(path):
    words = []
    seen = set()
    with path.open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            word = (row.get("word") or "").strip().casefold()
            if word and word not in seen:
                words.append(word)
                seen.add(word)
    return words


def clean_surface_form(value):
    word = value.strip().casefold()
    if not word:
        return "", "empty"
    if not word.isalpha():
        return "", "non_alpha"
    if len(word) <= 2 and word not in SHORT_ALLOWLIST:
        return "", "short_code"
    return word, ""


def load_forms(path, allowed_bases):
    forms_by_base = defaultdict(list)
    skipped = []
    with path.open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            base = (row.get("word") or "").strip().casefold()
            if base not in allowed_bases:
                continue
            seen_for_base = {base}
            for raw in (row.get("forms") or "").split("|"):
                form, reason = clean_surface_form(raw)
                if reason:
                    if raw.strip():
                        skipped.append({"base": base, "form": raw.strip(), "reason": reason})
                    continue
                if form in seen_for_base:
                    continue
                seen_for_base.add(form)
                forms_by_base[base].append(form)
    return forms_by_base, skipped


def load_entry_words(path):
    words = set()
    for item in path.glob("*.json"):
        try:
            data = json.loads(item.read_text(encoding="utf-8"))
        except Exception:
            continue
        word = (data.get("word") or "").strip().casefold()
        if word:
            words.add(word)
    return words


def write_words(path, words):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["word"])
        writer.writeheader()
        for word in words:
            writer.writerow({"word": word})


def write_details(path, rows, fieldnames):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Build a surface-word generation target list from kept core words and their forms."
    )
    parser.add_argument("--words", type=Path, default=Path("data/lemma-words.clean-r30000.csv"))
    parser.add_argument("--wordforms", type=Path, default=Path("data/lemma-wordforms.clean-r30000.csv"))
    parser.add_argument("--entries-dir", type=Path, default=Path("outputs/entries"))
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/core-surface-targets"))
    parser.add_argument("--targets", type=Path, default=Path("data/core-surface-words.csv"))
    parser.add_argument("--missing-targets", type=Path, default=Path("data/core-surface-missing-words.csv"))
    return parser.parse_args()


def main():
    args = parse_args()
    core_words = load_words(args.words)
    core_set = set(core_words)
    forms_by_base, skipped_forms = load_forms(args.wordforms, core_set)
    existing_entries = load_entry_words(args.entries_dir)

    ordered_targets = []
    target_source = {}
    seen = set()
    added_forms = []

    for base in core_words:
        if base not in seen:
            ordered_targets.append(base)
            target_source[base] = {"word": base, "source": "core", "base": base}
            seen.add(base)
        for form in forms_by_base.get(base, []):
            if form in seen:
                continue
            ordered_targets.append(form)
            target_source[form] = {"word": form, "source": "form", "base": base}
            added_forms.append({"word": form, "base": base})
            seen.add(form)

    missing_targets = [word for word in ordered_targets if word not in existing_entries]
    detail_rows = [target_source[word] for word in ordered_targets]
    missing_detail_rows = [target_source[word] for word in missing_targets]

    write_words(args.targets, ordered_targets)
    write_words(args.missing_targets, missing_targets)
    write_details(args.output_dir / "surface-target-details.csv", detail_rows, ["word", "source", "base"])
    write_details(args.output_dir / "missing-surface-target-details.csv", missing_detail_rows, ["word", "source", "base"])
    write_details(args.output_dir / "added-forms.csv", added_forms, ["word", "base"])
    write_details(args.output_dir / "skipped-forms.csv", skipped_forms, ["base", "form", "reason"])

    summary = {
        "source_words": str(args.words),
        "source_wordforms": str(args.wordforms),
        "entries_dir": str(args.entries_dir),
        "core_words": len(core_words),
        "surface_targets": len(ordered_targets),
        "added_forms": len(added_forms),
        "existing_entry_words": len(existing_entries),
        "missing_targets": len(missing_targets),
        "skipped_forms": len(skipped_forms),
        "outputs": {
            "targets": str(args.targets),
            "missing_targets": str(args.missing_targets),
            "details": str(args.output_dir / "surface-target-details.csv"),
            "missing_details": str(args.output_dir / "missing-surface-target-details.csv"),
            "added_forms": str(args.output_dir / "added-forms.csv"),
            "skipped_forms": str(args.output_dir / "skipped-forms.csv"),
        },
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
