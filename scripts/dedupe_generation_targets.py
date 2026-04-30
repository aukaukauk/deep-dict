#!/usr/bin/env python3
import argparse
import csv
import json
import tempfile
from collections import defaultdict
from pathlib import Path


DEFAULT_SOURCES = [
    ("oxford5000", Path("data/generation-targets/oxford5000/words.csv")),
    ("wordfreq-top10000-clean", Path("data/generation-targets/wordfreq-top10000-clean/words.csv")),
    ("lesswrong", Path("data/generation-targets/lesswrong/words.csv")),
    ("hacker-news", Path("data/generation-targets/hacker-news/words.csv")),
    ("reddit-comments", Path("data/generation-targets/reddit-comments/words.csv")),
]


def read_words(path):
    rows = []
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if "word" not in (reader.fieldnames or []):
            raise ValueError(f"{path} must contain a 'word' column")
        for index, row in enumerate(reader, 1):
            word = (row.get("word") or "").strip().casefold()
            if word:
                rows.append((word, index))
    return rows


def write_words_atomic(path, words):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        newline="",
        dir=str(path.parent),
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as f:
        tmp_path = Path(f.name)
        writer = csv.DictWriter(f, fieldnames=["word"])
        writer.writeheader()
        for word in words:
            writer.writerow({"word": word})
    tmp_path.replace(path)


def write_csv(path, rows, fieldnames):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def parse_source(value):
    if "=" not in value:
        raise argparse.ArgumentTypeError("source must be formatted as name=path")
    name, path = value.split("=", 1)
    name = name.strip()
    if not name:
        raise argparse.ArgumentTypeError("source name cannot be empty")
    return name, Path(path)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Deduplicate generation target word lists by priority order."
    )
    parser.add_argument(
        "--source",
        action="append",
        type=parse_source,
        help="Source in priority order, formatted as name=path. Can be repeated.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("outputs/wordlist-builds/dedupe-generation-targets"),
    )
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main():
    args = parse_args()
    sources = args.source or DEFAULT_SOURCES

    seen = {}
    retained_by_source = {}
    duplicates = []
    internal_duplicates = []
    original_counts = {}

    for source_index, (name, path) in enumerate(sources, 1):
        rows = read_words(path)
        original_counts[name] = len(rows)
        retained = []
        local_seen = {}
        for word, rank in rows:
            if word in local_seen:
                internal_duplicates.append(
                    {
                        "word": word,
                        "source": name,
                        "first_rank": local_seen[word],
                        "duplicate_rank": rank,
                    }
                )
                continue
            local_seen[word] = rank

            if word in seen:
                kept_source, kept_rank = seen[word]
                duplicates.append(
                    {
                        "word": word,
                        "kept_source": kept_source,
                        "kept_rank": kept_rank,
                        "duplicate_source": name,
                        "duplicate_rank": rank,
                    }
                )
                continue

            seen[word] = (name, rank)
            retained.append(word)

        retained_by_source[name] = {
            "path": path,
            "words": retained,
            "source_index": source_index,
        }

    if not args.dry_run:
        for item in retained_by_source.values():
            write_words_atomic(item["path"], item["words"])

    by_pair = defaultdict(int)
    for row in duplicates:
        by_pair[(row["kept_source"], row["duplicate_source"])] += 1
    overlap_rows = [
        {
            "kept_source": kept_source,
            "duplicate_source": duplicate_source,
            "duplicate_words": count,
        }
        for (kept_source, duplicate_source), count in sorted(by_pair.items())
    ]

    summary_rows = []
    for name, path in sources:
        retained_count = len(retained_by_source[name]["words"])
        duplicate_count = original_counts[name] - retained_count
        summary_rows.append(
            {
                "source": name,
                "path": str(path),
                "original_words": original_counts[name],
                "retained_words": retained_count,
                "removed_duplicates": duplicate_count,
            }
        )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(
        args.output_dir / "duplicates.csv",
        duplicates,
        ["word", "kept_source", "kept_rank", "duplicate_source", "duplicate_rank"],
    )
    write_csv(
        args.output_dir / "internal-duplicates.csv",
        internal_duplicates,
        ["word", "source", "first_rank", "duplicate_rank"],
    )
    write_csv(
        args.output_dir / "overlap-by-pair.csv",
        overlap_rows,
        ["kept_source", "duplicate_source", "duplicate_words"],
    )
    write_csv(
        args.output_dir / "summary.csv",
        summary_rows,
        ["source", "path", "original_words", "retained_words", "removed_duplicates"],
    )

    summary = {
        "dry_run": args.dry_run,
        "priority_order": [name for name, _path in sources],
        "unique_words": len(seen),
        "cross_source_duplicates": len(duplicates),
        "internal_duplicates": len(internal_duplicates),
        "sources": summary_rows,
        "outputs": {
            "duplicates": str(args.output_dir / "duplicates.csv"),
            "internal_duplicates": str(args.output_dir / "internal-duplicates.csv"),
            "overlap_by_pair": str(args.output_dir / "overlap-by-pair.csv"),
            "summary_csv": str(args.output_dir / "summary.csv"),
            "summary_json": str(args.output_dir / "summary.json"),
        },
    }
    (args.output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
