#!/usr/bin/env python3
import argparse
import csv
import hashlib
import html
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from build_lesswrong_wordlist import (
    cap_kind,
    capitalization_ratios,
    clean_chunk,
    load_ecdict_words_and_known_forms,
    load_known_wordforms,
    load_phrase_tokens,
    load_word_column,
    plural_canonical,
    reject_reason,
    write_csv,
    write_word_targets,
)


DELETED_BODIES = {"[deleted]", "[removed]", "deleted", "removed"}
BOT_AUTHORS = {"automoderator", "autowikibot", "tweetposter", "imgurtranscriber"}
SLANG_OR_ABBREVIATION_REVIEW = {
    "afaik",
    "ama",
    "aint",
    "arent",
    "cant",
    "couldnt",
    "dae",
    "devs",
    "didnt",
    "doesnt",
    "dont",
    "docs",
    "eli",
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
    "nsfw",
    "op",
    "pics",
    "psa",
    "smh",
    "tbh",
    "til",
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
TOKENIZED_NEGATIONS = {
    "ain": "am",
    "aren": "are",
    "can": "can",
    "couldn": "could",
    "didn": "did",
    "doesn": "does",
    "don": "do",
    "hadn": "had",
    "hasn": "has",
    "haven": "have",
    "isn": "is",
    "mustn": "must",
    "shouldn": "should",
    "wasn": "was",
    "weren": "were",
    "won": "will",
    "wouldn": "would",
}
TOKENIZED_CONTRACTIONS = {
    "i": {"m": "i am", "ve": "i have", "ll": "i will", "d": "i would"},
    "you": {"re": "you are", "ve": "you have", "ll": "you will", "d": "you would"},
    "we": {"re": "we are", "ve": "we have", "ll": "we will", "d": "we would"},
    "they": {"re": "they are", "ve": "they have", "ll": "they will", "d": "they would"},
    "he": {"s": "he is", "ll": "he will", "d": "he would"},
    "she": {"s": "she is", "ll": "she will", "d": "she would"},
    "it": {"s": "it is", "ll": "it will", "d": "it would"},
    "that": {"s": "that is"},
    "there": {"s": "there is"},
    "what": {"s": "what is"},
}


def parse_months(value):
    months = []
    for item in value.split(","):
        item = item.strip()
        if item:
            months.append(item)
    return months


def parse_utc(value):
    try:
        timestamp = int(value)
    except (TypeError, ValueError):
        return None
    return datetime.fromtimestamp(timestamp, timezone.utc)


def iter_reddit_rows(args, month):
    try:
        from datasets import load_dataset
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "Missing optional dependency. Install with: "
            "python3 -m pip install datasets huggingface_hub pyarrow"
        ) from exc

    return load_dataset(
        args.dataset,
        data_files=[f"data/RC_{month}.parquet"],
        split="train",
        streaming=True,
        columns=["id", "author", "body", "created_utc", "score", "subreddit"],
    )


def looks_like_bot(author):
    value = (author or "").strip().casefold()
    return value in BOT_AUTHORS or value.endswith("bot")


def normalize_reddit_body(body):
    text = html.unescape(str(body or "")).replace("\r\n", "\n")
    text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    text = re.sub(r"`[^`]*`", " ", text)
    text = re.sub(r"(?m)^\s*>.*$", " ", text)
    text = re.sub(r"\[\s*([^\]]+?)\s*\]\s*\(\s*[^)]*\)", r"\1", text)
    text = re.sub(r"\bhttps?\s*:\s*/\s*/(?:\s*\S+){1,40}", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\bwww\s*\.\s*(?:\s*\S+){1,20}", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"(?:^|\s)/?[ru]\s*/\s*[A-Za-z0-9_][A-Za-z0-9_-]*", " ", text)
    text = re.sub(r"\b[A-Za-z0-9.-]+\s*\.\s*(?:com|org|net|edu|gov|io|co|me)\b", " ", text, flags=re.IGNORECASE)
    for source, target in TOKENIZED_NEGATIONS.items():
        text = re.sub(rf"\b{source}\s+'\s+t\b", f"{target} not", text, flags=re.IGNORECASE)
    for pronoun, suffixes in TOKENIZED_CONTRACTIONS.items():
        for suffix, replacement in suffixes.items():
            text = re.sub(rf"\b{pronoun}\s+'\s+{suffix}\b", replacement, text, flags=re.IGNORECASE)
    return text


def clean_comment(body, args):
    raw = str(body or "").strip()
    if not raw:
        return "", "empty"
    if raw.casefold() in DELETED_BODIES:
        return "", "deleted_or_removed"
    if len(raw) > args.max_comment_chars:
        return "", "too_long_comment"

    text = normalize_reddit_body(raw)
    chunks = text.split()
    if len(chunks) < args.min_comment_tokens:
        return "", "too_short_comment"
    if len(chunks) > args.max_comment_tokens:
        return "", "too_long_comment"
    return text, ""


def reddit_reject_reason(row, args):
    word = row["word"]
    if word in PROFANITY_REVIEW:
        return "flagged_profanity"
    if word in SLANG_OR_ABBREVIATION_REVIEW:
        return "slang_or_abbreviation"
    reason = reject_reason(row, args)
    if reason:
        return reason
    if row["author_count"] < args.min_authors:
        return "low_author_count"
    if row["subreddit_count"] < args.min_subreddits:
        return "low_subreddit_count"
    return ""


def parse_args():
    parser = argparse.ArgumentParser(description="Build a cleaned Reddit Pushshift-derived generation word list.")
    parser.add_argument("--dataset", default="fddemarco/pushshift-reddit-comments")
    parser.add_argument("--months", default="2015-10,2015-11,2015-12")
    parser.add_argument("--known-words", type=Path, default=Path("data/generation-targets/oxford5000/words.csv"))
    parser.add_argument("--known-phrases", type=Path, default=Path("outputs/wordlist-builds/oxford5000/phrases.csv"))
    parser.add_argument("--known-wordforms", type=Path, default=Path("data/lemma-wordforms.csv"))
    parser.add_argument("--ecdict", type=Path, default=Path("vendor/ecdict/ecdict.csv"))
    parser.add_argument("--reference-words", type=Path, default=Path("data/ecdict-clean-words.csv"))
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/wordlist-builds/reddit-comments"))
    parser.add_argument("--targets", type=Path, default=Path("data/generation-targets/reddit-comments/words.csv"))
    parser.add_argument("--min-ecdict-count", type=int, default=5)
    parser.add_argument("--min-ecdict-docs", type=int, default=5)
    parser.add_argument("--min-non-ecdict-count", type=int, default=80)
    parser.add_argument("--min-non-ecdict-docs", type=int, default=30)
    parser.add_argument("--min-authors", type=int, default=5)
    parser.add_argument("--min-subreddits", type=int, default=3)
    parser.add_argument("--min-length", type=int, default=4)
    parser.add_argument("--max-length", type=int, default=28)
    parser.add_argument("--acronym-ratio", type=float, default=0.75)
    parser.add_argument("--proper-ratio", type=float, default=0.85)
    parser.add_argument("--min-lowercase-ratio", type=float, default=0.15)
    parser.add_argument("--min-comment-tokens", type=int, default=3)
    parser.add_argument("--max-comment-tokens", type=int, default=800)
    parser.add_argument("--max-comment-chars", type=int, default=8000)
    parser.add_argument("--review-limit", type=int, default=300)
    parser.add_argument("--sample-cleaned-limit", type=int, default=100)
    parser.add_argument("--limit-comments", type=int, help="Stop after N accepted comments; useful for smoke tests.")
    parser.add_argument("--limit-comments-per-month", type=int, help="Stop each month after N accepted comments.")
    parser.add_argument("--include-bots", action="store_true")
    return parser.parse_args()


def main():
    args = parse_args()
    known_words = load_word_column(args.known_words)
    known_words |= load_phrase_tokens(args.known_phrases)
    ecdict_words, known_forms, known_form_bases = load_ecdict_words_and_known_forms(args.ecdict, known_words)
    reference_words = load_word_column(args.reference_words) if args.reference_words.exists() else set()
    extra_known_forms, extra_known_form_bases = load_known_wordforms(args.known_wordforms, known_words)
    known_forms |= extra_known_forms
    known_form_bases.update(extra_known_form_bases)

    counter = Counter()
    doc_counter = Counter()
    author_counter = Counter()
    subreddit_counter = Counter()
    cap_counters = defaultdict(Counter)
    reject_chunks = Counter()
    reject_comments = Counter()
    comment_hashes = set()
    comments_seen = 0
    comments_used = 0
    comments_seen_by_month = Counter()
    comments_used_by_month = Counter()
    date_min = None
    date_max = None
    sample_cleaned = []

    stop_all = False
    for month in parse_months(args.months):
        month_used = 0
        for row in iter_reddit_rows(args, month):
            comments_seen += 1
            comments_seen_by_month[month] += 1
            author = (row.get("author") or "").strip()
            subreddit = (row.get("subreddit") or "").strip()
            if not args.include_bots and looks_like_bot(author):
                reject_comments["bot_author"] += 1
                continue

            created_at = parse_utc(row.get("created_utc"))
            if created_at:
                date_min = created_at if date_min is None else min(date_min, created_at)
                date_max = created_at if date_max is None else max(date_max, created_at)

            cleaned_text, comment_reason = clean_comment(row.get("body"), args)
            if comment_reason:
                reject_comments[comment_reason] += 1
                continue

            body_hash = hashlib.blake2b(cleaned_text.casefold().encode("utf-8"), digest_size=16).hexdigest()
            if body_hash in comment_hashes:
                reject_comments["duplicate_body"] += 1
                continue
            comment_hashes.add(body_hash)

            comment_words = []
            for chunk in cleaned_text.split():
                word, reason = clean_chunk(chunk)
                if reason:
                    reject_chunks[reason] += 1
                    continue
                comment_words.append((word, chunk))
            if not comment_words:
                reject_comments["no_clean_words"] += 1
                continue

            comments_used += 1
            month_used += 1
            comments_used_by_month[month] += 1
            unique_words = {word for word, _raw in comment_words}
            counter.update(word for word, _raw in comment_words)
            doc_counter.update(unique_words)
            if author:
                author_counter.update(unique_words)
            if subreddit:
                subreddit_counter.update(unique_words)
            for word, raw in comment_words:
                cap_counters[word][cap_kind(raw)] += 1

            if len(sample_cleaned) < args.sample_cleaned_limit:
                sample_cleaned.append(
                    {
                        "id": row.get("id"),
                        "created_utc": row.get("created_utc"),
                        "author": author,
                        "subreddit": subreddit,
                        "cleaned": cleaned_text[:1000],
                        "words": sorted(unique_words)[:80],
                    }
                )

            if args.limit_comments and comments_used >= args.limit_comments:
                stop_all = True
                break
            if args.limit_comments_per_month and month_used >= args.limit_comments_per_month:
                break
            if comments_seen % 500000 == 0:
                print(f"seen={comments_seen} used={comments_used}", flush=True)
        if stop_all:
            break

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
            "author_count": author_counter[word],
            "subreddit_count": subreddit_counter[word],
            "in_known": word in known_words,
            "known_inflection_base": known_base,
            "plural_canonical": plural_canonical(word, counter, reference_words, args.min_ecdict_count),
            "in_ecdict": word in ecdict_words,
            "in_reference": word in reference_words,
            **ratios,
        }
        row["reject_reason"] = reddit_reject_reason(row, args)
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
            existing["author_count"] = max(existing["author_count"], row["author_count"])
            existing["subreddit_count"] = max(existing["subreddit_count"], row["subreddit_count"])
            existing["variants"] = "|".join(sorted(set(existing["variants"].split("|") + [row["word"]])))
            existing["canonicalized"] = "yes"

    candidates = sorted(
        canonical_rows.values(),
        key=lambda row: (-row["subreddit_count"], -row["author_count"], -row["doc_count"], -row["count"], row["word"]),
    )
    target_words = [row["word"] for row in candidates]

    detail_fields = [
        "word",
        "count",
        "doc_count",
        "author_count",
        "subreddit_count",
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
        "author_count",
        "subreddit_count",
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
    with (args.output_dir / "sample-cleaned-comments.jsonl").open("w", encoding="utf-8") as f:
        for sample in sample_cleaned:
            f.write(json.dumps(sample, ensure_ascii=False) + "\n")

    summary = {
        "dataset": args.dataset,
        "months": parse_months(args.months),
        "comments_seen": comments_seen,
        "comments_used": comments_used,
        "comments_seen_by_month": dict(comments_seen_by_month),
        "comments_used_by_month": dict(comments_used_by_month),
        "date_min": date_min.isoformat() if date_min else None,
        "date_max": date_max.isoformat() if date_max else None,
        "known_words": str(args.known_words),
        "known_words_count": len(known_words),
        "known_forms_count": len(known_forms),
        "ecdict_words_count": len(ecdict_words),
        "reference_words_count": len(reference_words),
        "target_words": len(target_words),
        "reject_comments": dict(reject_comments.most_common()),
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
            "sample_cleaned_comments": str(args.output_dir / "sample-cleaned-comments.jsonl"),
        },
    }
    (args.output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)


if __name__ == "__main__":
    main()
