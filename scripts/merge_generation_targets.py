#!/usr/bin/env python3
import argparse
import csv
import json
from pathlib import Path


DEFAULT_SOURCES = [
    Path("data/generation-targets/wordfreq-r100000-clean/words.csv"),
    Path("data/generation-targets/oxford5000/words.csv"),
    Path("data/generation-targets/lesswrong/words.csv"),
    Path("data/generation-targets/hacker-news/words.csv"),
    Path("data/generation-targets/reddit-comments/words.csv"),
]


def read_words(path):
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if "word" not in (reader.fieldnames or []):
            raise ValueError(f"{path} must contain a 'word' column")
        for row in reader:
            word = (row.get("word") or "").strip().casefold()
            if word:
                yield word


def write_words(path, words):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["word"])
        writer.writeheader()
        for word in words:
            writer.writerow({"word": word})


def parse_args():
    parser = argparse.ArgumentParser(description="Merge generation target word CSV files into one word-only CSV.")
    parser.add_argument("--source", type=Path, action="append", help="Source words.csv. Can be repeated.")
    parser.add_argument(
        "--targets",
        type=Path,
        default=Path("data/generation-targets/merged-clean/words.csv"),
    )
    parser.add_argument(
        "--summary",
        type=Path,
        default=Path("outputs/wordlist-builds/merged-clean/summary.json"),
    )
    return parser.parse_args()


def main():
    args = parse_args()
    sources = args.source or DEFAULT_SOURCES
    seen = set()
    merged = []
    source_rows = []
    duplicate_count = 0

    for source in sources:
        source_total = 0
        source_added = 0
        for word in read_words(source):
            source_total += 1
            if word in seen:
                duplicate_count += 1
                continue
            seen.add(word)
            merged.append(word)
            source_added += 1
        source_rows.append(
            {
                "source": str(source),
                "source_words": source_total,
                "added_words": source_added,
            }
        )

    write_words(args.targets, merged)
    summary = {
        "targets": str(args.targets),
        "merged_words": len(merged),
        "duplicate_words_skipped": duplicate_count,
        "sources": source_rows,
    }
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
