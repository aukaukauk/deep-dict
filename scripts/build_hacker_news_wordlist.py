#!/usr/bin/env python3
import argparse
import csv
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from build_lesswrong_wordlist import (
    cap_kind,
    capitalization_ratios,
    clean_chunk,
    html_to_text,
    load_ecdict_words_and_known_forms,
    load_known_wordforms,
    load_phrase_tokens,
    load_word_column,
    plural_canonical,
    reject_reason,
    write_csv,
    write_word_targets,
)


TYPE_CODES = {
    "story": 1,
    "comment": 2,
    "poll": 3,
    "pollopt": 4,
    "job": 5,
}
SLANG_OR_ABBREVIATION_REVIEW = {
    "afaik",
    "aint",
    "arent",
    "btw",
    "cant",
    "couldnt",
    "didnt",
    "doesnt",
    "dont",
    "devs",
    "docs",
    "fwiw",
    "hadnt",
    "hasnt",
    "havent",
    "imho",
    "imo",
    "isnt",
    "irl",
    "lol",
    "lmao",
    "lmfao",
    "mods",
    "op",
    "pics",
    "smh",
    "tbh",
    "tl",
    "tldr",
    "wasnt",
    "werent",
    "wont",
    "wouldnt",
    "wtf",
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


def parse_years(value):
    years = []
    for item in value.split(","):
        item = item.strip()
        if item:
            years.append(int(item))
    return years


def parse_months(value):
    months = []
    for item in (value or "").split(","):
        item = item.strip()
        if item:
            months.append(item)
    return months


def data_files_for_args(args):
    months = parse_months(args.months)
    if months:
        return [f"data/{month[:4]}/{month}.parquet" for month in months]
    return [f"data/{year}/*.parquet" for year in parse_years(args.years)]


def row_chunks(row):
    words = row.get("words")
    if isinstance(words, list) and words:
        return [str(word) for word in words]
    text = html_to_text(" ".join(str(row.get(field) or "") for field in ("title", "text")))
    return text.split()


def parse_time(value):
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        timestamp = int(value)
    except (TypeError, ValueError):
        return None
    return datetime.fromtimestamp(timestamp, timezone.utc)


def hn_reject_reason(row, args):
    word = row["word"]
    if word in PROFANITY_REVIEW:
        return "flagged_profanity"
    if word in SLANG_OR_ABBREVIATION_REVIEW:
        return "slang_or_abbreviation"
    return reject_reason(row, args)


def iter_hn_rows(args):
    try:
        from datasets import load_dataset
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "Missing optional dependency. Install with: "
            "python3 -m pip install datasets huggingface_hub pyarrow"
        ) from exc

    return load_dataset(
        args.dataset,
        data_files=data_files_for_args(args),
        split="train",
        streaming=True,
        columns=["id", "type", "time", "title", "text", "score", "dead", "deleted", "words"],
    )


def parse_args():
    parser = argparse.ArgumentParser(description="Build a cleaned Hacker News-derived generation word list.")
    parser.add_argument("--dataset", default="open-index/hacker-news")
    parser.add_argument("--years", default="2025,2024", help="Comma-separated years, for example 2025,2024.")
    parser.add_argument("--months", help="Comma-separated YYYY-MM shards, for example 2025-01,2025-04. Overrides --years.")
    parser.add_argument("--types", default="story,comment", help="Comma-separated HN item types.")
    parser.add_argument("--known-words", type=Path, default=Path("data/generation-targets/oxford5000/words.csv"))
    parser.add_argument("--known-phrases", type=Path, default=Path("outputs/wordlist-builds/oxford5000/phrases.csv"))
    parser.add_argument("--known-wordforms", type=Path, default=Path("data/lemma-wordforms.csv"))
    parser.add_argument("--ecdict", type=Path, default=Path("vendor/ecdict/ecdict.csv"))
    parser.add_argument("--reference-words", type=Path, default=Path("data/ecdict-clean-words.csv"))
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/wordlist-builds/hacker-news"))
    parser.add_argument("--targets", type=Path, default=Path("data/generation-targets/hacker-news/words.csv"))
    parser.add_argument("--min-score", type=int, help="Optional score floor for story items only.")
    parser.add_argument("--min-ecdict-count", type=int, default=2)
    parser.add_argument("--min-ecdict-docs", type=int, default=2)
    parser.add_argument("--min-non-ecdict-count", type=int, default=30)
    parser.add_argument("--min-non-ecdict-docs", type=int, default=10)
    parser.add_argument("--min-length", type=int, default=4)
    parser.add_argument("--max-length", type=int, default=28)
    parser.add_argument("--acronym-ratio", type=float, default=0.75)
    parser.add_argument("--proper-ratio", type=float, default=0.85)
    parser.add_argument("--min-lowercase-ratio", type=float, default=0.15)
    parser.add_argument("--review-limit", type=int, default=300)
    parser.add_argument("--limit-items", type=int, help="Stop after N accepted HN items; useful for smoke tests.")
    return parser.parse_args()


def main():
    args = parse_args()
    selected_types = {TYPE_CODES[item.strip()] for item in args.types.split(",") if item.strip()}
    known_words = load_word_column(args.known_words)
    known_words |= load_phrase_tokens(args.known_phrases)
    ecdict_words, known_forms, known_form_bases = load_ecdict_words_and_known_forms(args.ecdict, known_words)
    reference_words = load_word_column(args.reference_words) if args.reference_words.exists() else set()
    extra_known_forms, extra_known_form_bases = load_known_wordforms(args.known_wordforms, known_words)
    known_forms |= extra_known_forms
    known_form_bases.update(extra_known_form_bases)

    counter = Counter()
    doc_counter = Counter()
    cap_counters = defaultdict(Counter)
    reject_chunks = Counter()
    item_counts = Counter()
    items_seen = 0
    items_used = 0
    date_min = None
    date_max = None

    for row in iter_hn_rows(args):
        items_seen += 1
        item_type = row.get("type")
        item_counts[str(item_type)] += 1
        if item_type not in selected_types:
            continue
        if row.get("deleted") or row.get("dead"):
            continue
        if args.min_score is not None and item_type == TYPE_CODES["story"]:
            score = row.get("score")
            if score is None or score < args.min_score:
                continue

        posted_at = parse_time(row.get("time"))
        if posted_at:
            date_min = posted_at if date_min is None else min(date_min, posted_at)
            date_max = posted_at if date_max is None else max(date_max, posted_at)

        item_words = []
        for chunk in row_chunks(row):
            word, reason = clean_chunk(chunk)
            if reason:
                reject_chunks[reason] += 1
                continue
            item_words.append((word, chunk))
        if not item_words:
            continue

        items_used += 1
        counter.update(word for word, _raw in item_words)
        doc_counter.update({word for word, _raw in item_words})
        for word, raw in item_words:
            cap_counters[word][cap_kind(raw)] += 1

        if args.limit_items and items_used >= args.limit_items:
            break
        if items_seen % 500000 == 0:
            print(f"seen={items_seen} used={items_used}", flush=True)

    raw_rows = []
    for word, count in counter.most_common():
        ratios = capitalization_ratios(cap_counters[word])
        known_base = ""
        if word in known_forms and word not in known_words:
            known_base = known_form_bases.get(word) or "known_form"
        row = {
            "word": word,
            "count": count,
            "doc_count": doc_counter[word],
            "in_known": word in known_words,
            "known_inflection_base": known_base,
            "plural_canonical": plural_canonical(word, counter, reference_words, args.min_ecdict_count),
            "in_ecdict": word in ecdict_words,
            "in_reference": word in reference_words,
            **ratios,
        }
        row["reject_reason"] = hn_reject_reason(row, args)
        raw_rows.append(row)

    canonical_rows = {}
    for row in raw_rows:
        if row["reject_reason"]:
            continue
        canonical = row["plural_canonical"] or row["word"]
        if canonical in known_words:
            continue
        existing = canonical_rows.get(canonical)
        if existing is None:
            canonical_rows[canonical] = {
                **row,
                "word": canonical,
                "variants": row["word"],
                "canonicalized": "yes" if canonical != row["word"] else "no",
            }
        else:
            existing["count"] += row["count"]
            existing["doc_count"] = max(existing["doc_count"], row["doc_count"])
            existing["variants"] = "|".join(sorted(set(existing["variants"].split("|") + [row["word"]])))
            existing["canonicalized"] = "yes"

    candidates = sorted(canonical_rows.values(), key=lambda row: (-row["doc_count"], -row["count"], row["word"]))
    target_words = [row["word"] for row in candidates]

    detail_fields = [
        "word",
        "count",
        "doc_count",
        "in_known",
        "known_inflection_base",
        "plural_canonical",
        "in_ecdict",
        "in_reference",
        "all_caps_ratio",
        "titlecase_ratio",
        "lowercase_ratio",
        "mixedcase_ratio",
        "reject_reason",
    ]
    candidate_fields = [
        "word",
        "count",
        "doc_count",
        "variants",
        "canonicalized",
        "in_ecdict",
        "in_reference",
        "all_caps_ratio",
        "titlecase_ratio",
        "lowercase_ratio",
        "mixedcase_ratio",
    ]

    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_word_targets(args.targets, target_words)
    write_csv(args.output_dir / "token-stats.csv", raw_rows, detail_fields)
    write_csv(args.output_dir / "candidates-detailed.csv", candidates, candidate_fields)
    write_csv(args.output_dir / "manual-review-top.csv", candidates[: args.review_limit], candidate_fields)
    write_csv(args.output_dir / "short-attention.csv", [row for row in raw_rows if row["reject_reason"] == "short_attention"], detail_fields)
    write_csv(args.output_dir / "proper-or-brand-like.csv", [row for row in raw_rows if row["reject_reason"] == "proper_or_brand_like"], detail_fields)
    write_csv(args.output_dir / "acronym-like.csv", [row for row in raw_rows if row["reject_reason"] == "acronym_like"], detail_fields)
    write_csv(args.output_dir / "slang-or-abbreviation.csv", [row for row in raw_rows if row["reject_reason"] == "slang_or_abbreviation"], detail_fields)
    write_csv(args.output_dir / "flagged-profanity-slurs.csv", [row for row in raw_rows if row["reject_reason"] == "flagged_profanity"], detail_fields)

    summary = {
        "dataset": args.dataset,
        "years": parse_years(args.years),
        "months": parse_months(args.months),
        "data_files": data_files_for_args(args),
        "types": args.types,
        "items_seen": items_seen,
        "items_used": items_used,
        "item_type_counts_seen": dict(item_counts.most_common()),
        "date_min": date_min.isoformat() if date_min else None,
        "date_max": date_max.isoformat() if date_max else None,
        "known_words": str(args.known_words),
        "known_words_count": len(known_words),
        "known_forms_count": len(known_forms),
        "ecdict_words_count": len(ecdict_words),
        "reference_words_count": len(reference_words),
        "target_words": len(target_words),
        "reject_chunks": dict(reject_chunks.most_common()),
        "reject_reasons": dict(Counter(row["reject_reason"] or "candidate" for row in raw_rows).most_common()),
        "outputs": {
            "targets": str(args.targets),
            "token_stats": str(args.output_dir / "token-stats.csv"),
            "candidates_detailed": str(args.output_dir / "candidates-detailed.csv"),
            "manual_review_top": str(args.output_dir / "manual-review-top.csv"),
            "short_attention": str(args.output_dir / "short-attention.csv"),
            "proper_or_brand_like": str(args.output_dir / "proper-or-brand-like.csv"),
            "acronym_like": str(args.output_dir / "acronym-like.csv"),
            "slang_or_abbreviation": str(args.output_dir / "slang-or-abbreviation.csv"),
            "flagged_profanity_slurs": str(args.output_dir / "flagged-profanity-slurs.csv"),
        },
    }
    (args.output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
