#!/usr/bin/env python3
import argparse
import csv
import json
from collections import Counter
from pathlib import Path


SINGLE_LETTER_ALLOWLIST = {"a", "i"}

SLANG_OR_ABBREVIATION_REVIEW = {
    "afaik",
    "aka",
    "ama",
    "brb",
    "btw",
    "dae",
    "eli",
    "fwiw",
    "idk",
    "imo",
    "imho",
    "irl",
    "lol",
    "lmao",
    "lmfao",
    "nsfw",
    "omg",
    "op",
    "psa",
    "smh",
    "tbh",
    "til",
    "tl",
    "tldr",
    "wtf",
}

CONTRACTION_SPELLINGS = {
    "aint",
    "arent",
    "cant",
    "couldnt",
    "didnt",
    "doesnt",
    "dont",
    "hadnt",
    "hasnt",
    "havent",
    "isnt",
    "wasnt",
    "werent",
    "wont",
    "wouldnt",
    "youre",
}

PROFANITY_REVIEW = {
    "arse",
    "asshole",
    "bastard",
    "bitch",
    "bullshit",
    "cunt",
    "damn",
    "dick",
    "fuck",
    "fucked",
    "fucker",
    "fucking",
    "motherfucker",
    "piss",
    "shit",
    "shitty",
    "slut",
    "whore",
}

ACRONYM_OR_NONWORD_REVIEW = {
    "ai",
    "api",
    "cia",
    "com",
    "css",
    "dvd",
    "eu",
    "faq",
    "fbi",
    "gps",
    "html",
    "http",
    "https",
    "irs",
    "jpg",
    "ml",
    "mp",
    "nba",
    "nfl",
    "pdf",
    "php",
    "sql",
    "uk",
    "ui",
    "usa",
    "ux",
    "www",
}


def read_rows(path, top_n):
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if "word" not in (reader.fieldnames or []):
            raise ValueError(f"{path} must contain a 'word' column")
        for index, row in enumerate(reader, 1):
            if index > top_n:
                break
            row = dict(row)
            row["source_index"] = index
            row["word"] = (row.get("word") or "").strip().casefold()
            yield row


def reject_reason(row):
    word = row["word"]
    token_type = row.get("token_type") or ""
    if not word:
        return "empty"
    if not word.isascii():
        return "non_ascii"
    if token_type and token_type != "alpha":
        return token_type
    if not word.isalpha():
        return "has_symbol_or_digit"
    if len(word) == 1 and word not in SINGLE_LETTER_ALLOWLIST:
        return "single_letter_noise"
    if word in CONTRACTION_SPELLINGS:
        return "contraction_spelling"
    if word in SLANG_OR_ABBREVIATION_REVIEW:
        return "slang_or_abbreviation"
    if word in ACRONYM_OR_NONWORD_REVIEW:
        return "acronym_or_nonword"
    if word in PROFANITY_REVIEW:
        return "flagged_profanity"
    return ""


def write_csv(path, rows, fieldnames):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_words(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["word"])
        writer.writeheader()
        for row in rows:
            writer.writerow({"word": row["word"]})


def parse_args():
    parser = argparse.ArgumentParser(description="Lightly clean the top N rows from a wordfreq target table.")
    parser.add_argument("--source", type=Path, default=Path("data/generation-targets/wordfreq-r100000/words.csv"))
    parser.add_argument("--top", type=int, default=10000)
    parser.add_argument("--targets", type=Path, default=Path("data/generation-targets/wordfreq-top10000-clean/words.csv"))
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/wordlist-builds/wordfreq-top10000-clean"))
    return parser.parse_args()


def main():
    args = parse_args()
    included = []
    excluded = []
    seen = set()
    reject_counter = Counter()

    for row in read_rows(args.source, args.top):
        reason = reject_reason(row)
        if row["word"] in seen:
            reason = "duplicate"
        if reason:
            row["exclude_reason"] = reason
            excluded.append(row)
            reject_counter[reason] += 1
            continue
        seen.add(row["word"])
        row["exclude_reason"] = ""
        included.append(row)

    fields = [
        "word",
        "source_index",
        "wordfreq_rank",
        "zipf_frequency",
        "token_type",
        "in_known",
        "exclude_reason",
    ]
    write_words(args.targets, included)
    write_csv(args.output_dir / "included.csv", included, fields)
    write_csv(args.output_dir / "excluded.csv", excluded, fields)

    summary = {
        "source": str(args.source),
        "top": args.top,
        "targets": str(args.targets),
        "included_words": len(included),
        "excluded_words": len(excluded),
        "reject_reasons": dict(reject_counter.most_common()),
        "note": "Conservative first-pass cleanup. Proper nouns and brand/platform names are mostly left for the LLM include/exclude step.",
        "outputs": {
            "included": str(args.output_dir / "included.csv"),
            "excluded": str(args.output_dir / "excluded.csv"),
            "summary": str(args.output_dir / "summary.json"),
        },
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
