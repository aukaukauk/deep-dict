#!/usr/bin/env python3
"""Convert between the entries archive and the working directory.

  unpack: dictionary/entries.jsonl.gz -> work/entries/ (one JSON per word)
  pack:   work/entries/ -> dictionary/entries.jsonl.gz, and refresh
          dictionary/included-words.csv

Usage:
  python3 -m deepdict.cli.archive unpack
  python3 -m deepdict.cli.archive pack
"""

import argparse
from pathlib import Path

from ..entries import pack_entries, unpack_entries


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("action", choices=["pack", "unpack"])
    parser.add_argument("--archive", type=Path, default=Path("dictionary/entries.jsonl.gz"))
    parser.add_argument("--entries-dir", type=Path, default=Path("work/entries"))
    parser.add_argument("--included-words", type=Path, default=Path("dictionary/included-words.csv"))
    return parser.parse_args()


def main():
    args = parse_args()
    if args.action == "unpack":
        count = unpack_entries(args.archive, args.entries_dir)
        print(f"unpacked={count} dir={args.entries_dir}")
        return
    entries = pack_entries(args.entries_dir, args.archive)
    included = sorted(entry["word"] for entry in entries if entry.get("include"))
    with args.included_words.open("w", encoding="utf-8", newline="") as f:
        f.write("word\n")
        f.writelines(f"{word}\n" for word in included)
    print(f"packed={len(entries)} included={len(included)} archive={args.archive}")


if __name__ == "__main__":
    main()
