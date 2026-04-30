#!/usr/bin/env python3
import argparse
import csv
import json
from collections import Counter
from pathlib import Path

from filter_ecdict_main_words import SHORT_ALLOWLIST, reject_reason


DIRTY_REASONS = {
    "no_evidence",
    "abbreviation",
    "domain_code_only",
    "short_abbreviation",
    "repeated_noise",
    "short_code",
    "inflection_only",
    "non_lowercase_or_acronym",
    "proper_name",
}


def load_current_words(path):
    words = []
    with path.open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            word = (row.get("word") or "").strip()
            if word:
                words.append(word.casefold())
    return words


def load_wordforms(path):
    rows = {}
    with path.open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            word = (row.get("word") or "").strip().casefold()
            if word:
                rows[word] = {"word": word, "forms": row.get("forms") or ""}
    return rows


def load_ecdict_rows(path):
    rows = {}
    with path.open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            word = (row.get("word") or "").strip()
            key = word.casefold()
            if word and word.isalpha() and key not in rows:
                rows[key] = row
    return rows


def entry_paths_by_word(entries_dir):
    mapping = {}
    errors = []
    for path in entries_dir.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            word = (data.get("word") or "").strip().casefold()
            if word:
                mapping[word] = path
        except Exception as exc:
            errors.append({"file": str(path), "error": str(exc)})
    return mapping, errors


def classify(word, rank, ecdict_rows, rank_cutoff):
    if len(word) <= 2 and word not in SHORT_ALLOWLIST:
        return "remove", "short_code"

    row = ecdict_rows.get(word)
    if row is None:
        if rank > rank_cutoff:
            return "remove", "not_in_ecdict_tail"
        return "keep", "high_rank_not_in_ecdict"

    reason = reject_reason(row)
    if rank > rank_cutoff and reason in DIRTY_REASONS:
        return "remove", reason
    if reason:
        return "keep", f"high_rank_{reason}"
    return "keep", "ecdict_evidence"


def write_words(path, words):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["word"])
        writer.writeheader()
        for word in words:
            writer.writerow({"word": word})


def write_wordforms(path, words, wordform_rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["word", "forms"])
        writer.writeheader()
        for word in words:
            row = wordform_rows.get(word, {"word": word, "forms": ""})
            writer.writerow(row)


def write_decisions(path, decisions):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        fieldnames = ["word", "rank", "decision", "reason", "entry_path"]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for item in decisions:
            writer.writerow(item)


def parse_args():
    parser = argparse.ArgumentParser(description="Plan cleanup of the current generated lexicon and entry files.")
    parser.add_argument("--words", type=Path, default=Path("data/lemma-words.csv"))
    parser.add_argument("--wordforms", type=Path, default=Path("data/lemma-wordforms.csv"))
    parser.add_argument("--ecdict", type=Path, default=Path("vendor/ecdict/ecdict.csv"))
    parser.add_argument("--entries-dir", type=Path, default=Path("outputs/entries"))
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/current-lexicon-cleanup"))
    parser.add_argument("--clean-words", type=Path, default=Path("data/lemma-words.clean.csv"))
    parser.add_argument("--clean-wordforms", type=Path, default=Path("data/lemma-wordforms.clean.csv"))
    parser.add_argument("--rank-cutoff", type=int, default=50000)
    return parser.parse_args()


def main():
    args = parse_args()
    words = load_current_words(args.words)
    wordforms = load_wordforms(args.wordforms)
    ecdict_rows = load_ecdict_rows(args.ecdict)
    entry_paths, entry_errors = entry_paths_by_word(args.entries_dir)

    keep_words = []
    remove_words = []
    decisions = []
    reason_counts = Counter()
    remove_reason_counts = Counter()
    missing_entries = []

    for rank, word in enumerate(words, 1):
        decision, reason = classify(word, rank, ecdict_rows, args.rank_cutoff)
        entry_path = entry_paths.get(word)
        item = {
            "word": word,
            "rank": rank,
            "decision": decision,
            "reason": reason,
            "entry_path": str(entry_path) if entry_path else "",
        }
        decisions.append(item)
        reason_counts[f"{decision}:{reason}"] += 1
        if decision == "keep":
            keep_words.append(word)
        else:
            remove_words.append(word)
            remove_reason_counts[reason] += 1
            if entry_path is None:
                missing_entries.append(word)

    write_words(args.clean_words, keep_words)
    write_wordforms(args.clean_wordforms, keep_words, wordforms)
    write_decisions(args.output_dir / "decisions.csv", decisions)
    write_decisions(args.output_dir / "remove-candidates.csv", [d for d in decisions if d["decision"] == "remove"])
    write_decisions(args.output_dir / "keep-candidates.csv", [d for d in decisions if d["decision"] == "keep"])

    entries_to_delete = [d["entry_path"] for d in decisions if d["decision"] == "remove" and d["entry_path"]]
    (args.output_dir / "entries-to-delete.txt").write_text("\n".join(entries_to_delete) + ("\n" if entries_to_delete else ""), encoding="utf-8")

    summary = {
        "rank_cutoff": args.rank_cutoff,
        "source_words": str(args.words),
        "source_wordforms": str(args.wordforms),
        "entries_dir": str(args.entries_dir),
        "current_words": len(words),
        "keep_words": len(keep_words),
        "remove_words": len(remove_words),
        "entries_found": len(entry_paths),
        "entries_to_delete": len(entries_to_delete),
        "remove_missing_entry_files": len(missing_entries),
        "entry_read_errors": entry_errors,
        "remove_reasons": dict(remove_reason_counts.most_common()),
        "decision_reasons": dict(reason_counts.most_common()),
        "outputs": {
            "clean_words": str(args.clean_words),
            "clean_wordforms": str(args.clean_wordforms),
            "decisions": str(args.output_dir / "decisions.csv"),
            "remove_candidates": str(args.output_dir / "remove-candidates.csv"),
            "keep_candidates": str(args.output_dir / "keep-candidates.csv"),
            "entries_to_delete": str(args.output_dir / "entries-to-delete.txt"),
        },
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
