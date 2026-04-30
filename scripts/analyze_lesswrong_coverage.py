#!/usr/bin/env python3
import argparse
import csv
import html
import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path


WORD_RE = re.compile(r"[A-Za-z]+(?:['’][A-Za-z]+)?")
SKIP_TAGS = {"script", "style", "code", "pre", "math", "mjx-container"}
CONTRACTION_BASES = {
    "can't": "can",
    "cannot": "can",
    "won't": "will",
    "shan't": "shall",
}


class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag.lower() in SKIP_TAGS:
            self.skip_depth += 1

    def handle_endtag(self, tag):
        if tag.lower() in SKIP_TAGS and self.skip_depth:
            self.skip_depth -= 1

    def handle_data(self, data):
        if not self.skip_depth and data:
            self.parts.append(data)

    def text(self):
        return " ".join(self.parts)


def html_to_text(value):
    if not value:
        return ""
    parser = TextExtractor()
    try:
        parser.feed(value)
        parser.close()
        return parser.text()
    except Exception:
        return re.sub(r"<[^>]+>", " ", html.unescape(value))


def normalize_token(raw):
    token = raw.replace("’", "'").casefold().strip("'")
    if not token:
        return None
    if token in CONTRACTION_BASES:
        token = CONTRACTION_BASES[token]
    elif token.endswith("n't"):
        token = token[:-3]
    else:
        for suffix in ("'s", "'re", "'ve", "'ll", "'d", "'m"):
            if token.endswith(suffix):
                token = token[: -len(suffix)]
                break
    token = token.replace("'", "")
    if not token.isalpha():
        return None
    return token


def cap_kind(raw):
    raw = raw.replace("’", "'").strip("'")
    if len(raw) >= 2 and raw.isupper():
        return "all_caps"
    if raw.islower():
        return "lower"
    if len(raw) >= 2 and raw[0].isupper() and raw[1:].islower():
        return "title"
    return "mixed"


def read_dictionary_sets(words_path, wordforms_path):
    headwords = set()
    with words_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            word = (row.get("word") or "").strip()
            if word:
                headwords.add(word.casefold())

    search_terms = set(headwords)
    with wordforms_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            word = (row.get("word") or "").strip()
            if word:
                search_terms.add(word.casefold())
            for form in (row.get("forms") or "").split("|"):
                form = form.strip()
                if form:
                    search_terms.add(form.casefold())

    return headwords, search_terms


def post_text(post):
    title = post.get("title") or ""
    contents = post.get("contents") or {}
    body = html_to_text(contents.get("html") or "")
    return f"{title}\n{body}"


def parse_date(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def token_rows(counter, doc_counter, cap_counter, headwords, search_terms):
    for word, count in counter.most_common():
        caps = cap_counter[word]
        total_caps = sum(caps.values()) or 1
        yield {
            "word": word,
            "count": count,
            "doc_count": doc_counter[word],
            "in_headwords": word in headwords,
            "in_search_terms": word in search_terms,
            "all_caps_ratio": caps["all_caps"] / total_caps,
            "titlecase_ratio": caps["title"] / total_caps,
            "lowercase_ratio": caps["lower"] / total_caps,
            "mixedcase_ratio": caps["mixed"] / total_caps,
        }


def is_clean_candidate(row, min_count, min_docs):
    if row["in_search_terms"]:
        return False
    word = row["word"]
    if not (4 <= len(word) <= 32):
        return False
    if row["count"] < min_count or row["doc_count"] < min_docs:
        return False
    if row["all_caps_ratio"] >= 0.75 and len(word) <= 8:
        return False
    if row["titlecase_ratio"] >= 0.85 and row["lowercase_ratio"] < 0.1:
        return False
    return True


def summarize(counter, doc_counter, headwords, search_terms):
    total_tokens = sum(counter.values())
    unique_tokens = len(counter)
    headword_tokens = sum(count for word, count in counter.items() if word in headwords)
    search_tokens = sum(count for word, count in counter.items() if word in search_terms)
    headword_types = sum(1 for word in counter if word in headwords)
    search_types = sum(1 for word in counter if word in search_terms)
    return {
        "total_tokens": total_tokens,
        "unique_tokens": unique_tokens,
        "headword_covered_tokens": headword_tokens,
        "search_term_covered_tokens": search_tokens,
        "headword_missing_tokens": total_tokens - headword_tokens,
        "search_term_missing_tokens": total_tokens - search_tokens,
        "headword_covered_types": headword_types,
        "search_term_covered_types": search_types,
        "headword_missing_types": unique_tokens - headword_types,
        "search_term_missing_types": unique_tokens - search_types,
        "headword_token_coverage": headword_tokens / total_tokens if total_tokens else 0,
        "search_term_token_coverage": search_tokens / total_tokens if total_tokens else 0,
        "headword_type_coverage": headword_types / unique_tokens if unique_tokens else 0,
        "search_term_type_coverage": search_types / unique_tokens if unique_tokens else 0,
    }


def write_csv(path, rows, limit=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "word",
        "count",
        "doc_count",
        "in_headwords",
        "in_search_terms",
        "all_caps_ratio",
        "titlecase_ratio",
        "lowercase_ratio",
        "mixedcase_ratio",
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for idx, row in enumerate(rows):
            if limit is not None and idx >= limit:
                break
            writer.writerow(row)


def parse_args():
    parser = argparse.ArgumentParser(description="Analyze LessWrong corpus coverage against the dictionary word list.")
    parser.add_argument("--corpus", type=Path, default=Path("/Users/haique/Downloads/lesswrong_full.json"))
    parser.add_argument("--words", type=Path, default=Path("data/lemma-words.csv"))
    parser.add_argument("--wordforms", type=Path, default=Path("data/lemma-wordforms.csv"))
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/lesswrong-coverage"))
    parser.add_argument("--min-candidate-count", type=int, default=5)
    parser.add_argument("--min-candidate-docs", type=int, default=3)
    parser.add_argument("--csv-limit", type=int, default=5000)
    parser.add_argument("--thresholds", default="0,10,25,50")
    return parser.parse_args()


def main():
    args = parse_args()
    thresholds = sorted({int(value) for value in args.thresholds.split(",") if value.strip()})
    bucket_names = {threshold: ("all" if threshold == 0 else f"score_gte_{threshold}") for threshold in thresholds}

    headwords, search_terms = read_dictionary_sets(args.words, args.wordforms)

    counters = {threshold: Counter() for threshold in thresholds}
    doc_counters = {threshold: Counter() for threshold in thresholds}
    cap_counters = {threshold: defaultdict(Counter) for threshold in thresholds}
    post_counts = {threshold: 0 for threshold in thresholds}
    date_min = None
    date_max = None

    with args.corpus.open("r", encoding="utf-8") as f:
        posts = json.load(f)["data"]["posts"]["results"]

    for index, post in enumerate(posts, 1):
        score = post.get("baseScore") or 0
        posted_at = parse_date(post.get("postedAt"))
        if posted_at:
            date_min = posted_at if date_min is None else min(date_min, posted_at)
            date_max = posted_at if date_max is None else max(date_max, posted_at)

        raw_tokens = []
        for match in WORD_RE.finditer(post_text(post)):
            word = normalize_token(match.group(0))
            if word and len(word) >= 2:
                raw_tokens.append((word, match.group(0)))

        if not raw_tokens:
            continue

        doc_words = {word for word, _raw in raw_tokens}
        for threshold in thresholds:
            if threshold and score < threshold:
                continue
            post_counts[threshold] += 1
            counters[threshold].update(word for word, _raw in raw_tokens)
            doc_counters[threshold].update(doc_words)
            cap_counter = cap_counters[threshold]
            for word, raw in raw_tokens:
                cap_counter[word][cap_kind(raw)] += 1

        if index % 5000 == 0:
            print(f"processed={index}/{len(posts)}")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    summary = {
        "corpus": str(args.corpus),
        "posts_total": len(posts),
        "date_min": date_min.isoformat() if date_min else None,
        "date_max": date_max.isoformat() if date_max else None,
        "dictionary_headwords": len(headwords),
        "dictionary_search_terms": len(search_terms),
        "buckets": {},
    }

    for threshold in thresholds:
        name = bucket_names[threshold]
        rows = list(token_rows(counters[threshold], doc_counters[threshold], cap_counters[threshold], headwords, search_terms))
        missing_rows = [row for row in rows if not row["in_search_terms"]]
        candidate_rows = [
            row
            for row in missing_rows
            if is_clean_candidate(row, args.min_candidate_count, args.min_candidate_docs)
        ]
        acronym_rows = [
            row
            for row in missing_rows
            if row["all_caps_ratio"] >= 0.75 and 2 <= len(row["word"]) <= 8 and row["count"] >= args.min_candidate_count
        ]
        proper_rows = [
            row
            for row in missing_rows
            if row["titlecase_ratio"] >= 0.85 and row["lowercase_ratio"] < 0.1 and row["count"] >= args.min_candidate_count
        ]

        bucket_summary = summarize(counters[threshold], doc_counters[threshold], headwords, search_terms)
        bucket_summary.update(
            {
                "posts": post_counts[threshold],
                "clean_candidate_types": len(candidate_rows),
                "clean_candidate_tokens": sum(row["count"] for row in candidate_rows),
                "acronym_like_missing_types": len(acronym_rows),
                "proper_like_missing_types": len(proper_rows),
            }
        )
        summary["buckets"][name] = bucket_summary

        write_csv(args.output_dir / f"{name}.missing_all.csv", missing_rows, args.csv_limit)
        write_csv(args.output_dir / f"{name}.missing_candidates.csv", candidate_rows, args.csv_limit)
        write_csv(args.output_dir / f"{name}.missing_acronym_like.csv", acronym_rows, args.csv_limit)
        write_csv(args.output_dir / f"{name}.missing_proper_like.csv", proper_rows, args.csv_limit)

    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
