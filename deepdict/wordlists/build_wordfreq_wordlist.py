#!/usr/bin/env python3
import argparse
import csv
import json
import re
from collections import Counter
from pathlib import Path

from wordfreq import iter_wordlist, zipf_frequency


CONTRACTION_RE = re.compile(r"^[a-z]+(?:'[a-z]+)+$")
SINGLE_LETTER_ALLOWLIST = {"a", "i"}


def load_word_column(path):
    words = set()
    if not path.exists():
        return words
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if "word" not in (reader.fieldnames or []):
            raise ValueError(f"{path} must contain a 'word' column")
        for row in reader:
            word = (row.get("word") or "").strip().casefold()
            if word:
                words.add(word)
    return words


def classify_token(token, include_contractions):
    if not token:
        return "empty", "empty"
    if not token.isascii():
        return "non_ascii", "non_ascii"
    if any(char.isdigit() for char in token):
        return "has_digit", "has_digit"
    if len(token) == 1 and token not in SINGLE_LETTER_ALLOWLIST:
        return "single_letter_noise", "single_letter_noise"
    if token.isalpha():
        return "alpha", ""
    if include_contractions and CONTRACTION_RE.fullmatch(token):
        return "contraction", ""
    return "has_symbol", "has_symbol"


def write_csv(path, rows, fieldnames):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def parse_args():
    parser = argparse.ArgumentParser(description="Build a generation target list from wordfreq rankings.")
    parser.add_argument("--lang", default="en")
    parser.add_argument("--limit", type=int, default=1000, help="Number of accepted tokens to write.")
    parser.add_argument("--wordlist", default="best")
    parser.add_argument("--ascii-only", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--include-contractions", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--known-words", type=Path, default=Path("data/generation-targets/oxford5000/words.csv"))
    parser.add_argument("--output-dir", type=Path, help="Side-table output directory.")
    parser.add_argument("--targets", type=Path, help="Generation target CSV path.")
    return parser.parse_args()


def main():
    args = parse_args()
    suffix = f"wordfreq-r{args.limit}"
    output_dir = args.output_dir or Path("outputs/wordlist-builds") / suffix
    targets = args.targets or Path("data/generation-targets") / suffix / "words.csv"

    known_words = load_word_column(args.known_words)
    accepted = []
    excluded = []
    raw_rows = []
    seen = set()
    reject_counter = Counter()

    for rank, token in enumerate(iter_wordlist(args.lang, wordlist=args.wordlist), 1):
        word = token.casefold()
        if args.ascii_only and not word.isascii():
            token_type, reject_reason = "non_ascii", "non_ascii"
        else:
            token_type, reject_reason = classify_token(word, args.include_contractions)

        row = {
            "word": word,
            "wordfreq_rank": rank,
            "zipf_frequency": f"{zipf_frequency(word, args.lang, wordlist=args.wordlist):.2f}",
            "token_type": token_type,
            "in_known": "yes" if word in known_words else "no",
            "include_for_generation": "no" if reject_reason else "yes",
            "exclude_reason": reject_reason,
        }

        if word in seen:
            row["include_for_generation"] = "no"
            row["exclude_reason"] = "duplicate"
        raw_rows.append(row)

        if row["exclude_reason"]:
            excluded.append(row)
            reject_counter[row["exclude_reason"]] += 1
            continue

        seen.add(word)
        accepted.append(row)
        if len(accepted) >= args.limit:
            break

    fields = [
        "word",
        "wordfreq_rank",
        "zipf_frequency",
        "token_type",
        "in_known",
        "include_for_generation",
        "exclude_reason",
    ]
    write_csv(targets, accepted, fields)
    write_csv(output_dir / "raw-scanned.csv", raw_rows, fields)
    write_csv(output_dir / "excluded.csv", excluded, fields)
    write_csv(output_dir / "known-overlap.csv", [row for row in accepted if row["in_known"] == "yes"], fields)

    summary = {
        "source": "wordfreq",
        "lang": args.lang,
        "wordlist": args.wordlist,
        "limit": args.limit,
        "ascii_only": args.ascii_only,
        "include_contractions": args.include_contractions,
        "raw_items_scanned": len(raw_rows),
        "accepted_words": len(accepted),
        "excluded_items": len(excluded),
        "reject_reasons": dict(reject_counter.most_common()),
        "known_words": str(args.known_words),
        "known_overlap": sum(1 for row in accepted if row["in_known"] == "yes"),
        "outputs": {
            "targets": str(targets),
            "raw_scanned": str(output_dir / "raw-scanned.csv"),
            "excluded": str(output_dir / "excluded.csv"),
            "known_overlap": str(output_dir / "known-overlap.csv"),
        },
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
