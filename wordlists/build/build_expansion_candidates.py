#!/usr/bin/env python3
"""Build the candidate lists for expanding the dictionary beyond the first 100k words.

Nothing here judges whether a word is worth including: that is left to the
generating model. Only forms that can be ruled out mechanically are dropped
(digits, symbols, non-ASCII letters, possessives).

Outputs, each a one-column `word` CSV:
  wordlists/ecdict-tagged.csv   single words that ECDICT marks as belonging to a
                                learner or exam list (Collins, Oxford, exam tags)
                                and that are not in the dictionary yet
  wordlists/contractions.csv    apostrophe forms from wordfreq that are not
                                possessives (it's, they'd, o'clock, ...)
  wordlists/wordfreq-rest.csv   every remaining pure-letter wordfreq entry,
                                most frequent first
A word already present in dictionary/entries.jsonl.gz (included or excluded)
is never listed again.
"""
import argparse
import csv
import re
import sys
from pathlib import Path

from wordfreq import iter_wordlist

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from deepdict.entries import iter_entries  # noqa: E402

CONTRACTION = re.compile(r"[a-z]+(?:'[a-z]+)+")


def write(path, words):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        f.write("word\n")
        f.writelines(f"{w}\n" for w in words)
    print(f"{path}: {len(words)}")


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--entries", type=Path, default=Path("dictionary/entries.jsonl.gz"))
    parser.add_argument("--ecdict", type=Path, default=Path("work/vendor/ecdict/ecdict.csv"))
    parser.add_argument("--out-dir", type=Path, default=Path("wordlists"))
    return parser.parse_args()


def main():
    args = parse_args()
    csv.field_size_limit(10**9)
    seen = {entry["word"].lower() for entry in iter_entries(args.entries)}

    tagged = []
    with args.ecdict.open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            word = row["word"]
            marked = row.get("tag", "").strip() or row.get("collins", "") not in ("", "0") or row.get("oxford", "") not in ("", "0")
            if marked and word.isascii() and word.isalpha() and word.islower() and word not in seen:
                tagged.append(word)
    tagged = sorted(set(tagged))
    taken = seen | set(tagged)

    contractions, rest = [], []
    for word in iter_wordlist("en", "best"):
        if word.lower() in taken:
            continue
        if word.isascii() and word.isalpha():
            rest.append(word)
            taken.add(word.lower())
        elif word.isascii() and CONTRACTION.fullmatch(word) and not (word.endswith("'s") or word.endswith("s'")):
            contractions.append(word)
            taken.add(word.lower())

    write(args.out_dir / "ecdict-tagged.csv", tagged)
    write(args.out_dir / "contractions.csv", contractions)
    write(args.out_dir / "wordfreq-rest.csv", rest)


if __name__ == "__main__":
    main()
