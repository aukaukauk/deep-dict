#!/usr/bin/env python3
import argparse
import csv
import html
import json
import re
import string
from collections import Counter, defaultdict
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path


SKIP_TAGS = {"script", "style", "code", "pre", "math", "mjx-container"}
EDGE_PUNCT = string.punctuation + "“”‘’—–…·•、，。！？；：（）【】《》"
SHORT_ALLOWLIST = {
    "act",
    "aid",
    "aim",
    "air",
    "art",
    "ask",
    "bay",
    "bit",
    "box",
    "buy",
    "cap",
    "car",
    "cat",
    "cry",
    "cut",
    "day",
    "die",
    "dog",
    "dry",
    "ear",
    "eat",
    "egg",
    "end",
    "eye",
    "far",
    "fat",
    "fit",
    "fix",
    "fly",
    "fun",
    "gas",
    "god",
    "gun",
    "guy",
    "hat",
    "hit",
    "hot",
    "ice",
    "ill",
    "job",
    "joy",
    "key",
    "law",
    "lay",
    "leg",
    "lie",
    "lip",
    "lot",
    "low",
    "map",
    "net",
    "new",
    "odd",
    "oil",
    "old",
    "one",
    "own",
    "pay",
    "per",
    "pop",
    "raw",
    "red",
    "run",
    "sad",
    "sea",
    "see",
    "sex",
    "sky",
    "tax",
    "tea",
    "tie",
    "top",
    "try",
    "two",
    "war",
    "way",
    "wet",
    "win",
    "yes",
    "yet",
}
PLURAL_EXCEPTIONS = {
    "analysis",
    "basis",
    "bias",
    "business",
    "chaos",
    "class",
    "consciousness",
    "crisis",
    "ethics",
    "gas",
    "genius",
    "glass",
    "herpes",
    "hypothesis",
    "less",
    "loss",
    "mathematics",
    "news",
    "physics",
    "politics",
    "progress",
    "series",
    "species",
    "status",
    "success",
    "thesis",
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


def clean_chunk(chunk):
    stripped = chunk.strip(EDGE_PUNCT)
    if not stripped:
        return "", "empty"
    if not stripped.isascii():
        return "", "non_ascii"
    if not stripped.isalpha():
        if any(char.isdigit() for char in stripped):
            return "", "has_digit"
        return "", "has_symbol"
    return stripped.casefold(), ""


def cap_kind(raw):
    raw = raw.strip(EDGE_PUNCT)
    if len(raw) >= 2 and raw.isupper():
        return "all_caps"
    if raw.islower():
        return "lower"
    if len(raw) >= 2 and raw[0].isupper() and raw[1:].islower():
        return "title"
    return "mixed"


def load_word_column(path):
    words = set()
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if "word" not in (reader.fieldnames or []):
            raise ValueError(f"{path} must contain a 'word' column")
        for row in reader:
            word = (row.get("word") or "").strip().casefold()
            if word:
                words.add(word)
    return words


def exchange_values(exchange):
    values = []
    for part in (exchange or "").split("/"):
        if ":" not in part:
            continue
        _kind, value = part.split(":", 1)
        value = value.strip().casefold()
        if value and value.isalpha():
            values.append(value)
    return values


def load_phrase_tokens(path):
    tokens = set()
    if not path.exists():
        return tokens
    with path.open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            for token in (row.get("word") or "").casefold().split():
                if token.isalpha():
                    tokens.add(token)
    return tokens


def load_known_wordforms(path, known_words):
    known_forms = set()
    known_form_bases = {}
    if not path.exists():
        return known_forms, known_form_bases
    with path.open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            word = (row.get("word") or "").strip().casefold()
            if word not in known_words:
                continue
            for form in (row.get("forms") or "").split("|"):
                form = form.strip().casefold()
                if form and form.isalpha():
                    known_forms.add(form)
                    known_form_bases.setdefault(form, word)
    return known_forms, known_form_bases


def load_ecdict_words_and_known_forms(path, known_words):
    if not path.exists():
        return set(), set(known_words), {}
    words = set()
    known_forms = set(known_words)
    known_form_bases = {}
    with path.open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            word = (row.get("word") or "").strip().casefold()
            if word and word.isalpha():
                words.add(word)
            exchange = row.get("exchange") or ""
            values = exchange_values(exchange)
            if word in known_words:
                for value in values:
                    known_forms.add(value)
                    known_form_bases.setdefault(value, word)
            for value in values:
                if value in known_words:
                    known_forms.add(word)
                    known_form_bases.setdefault(word, value)
    return words, known_forms, known_form_bases


def possible_plural_bases(word):
    bases = []
    if word in PLURAL_EXCEPTIONS or len(word) <= 4:
        return bases
    if word.endswith("ies"):
        bases.append(word[:-3] + "y")
    if word.endswith("ves"):
        bases.extend([word[:-3] + "f", word[:-3] + "fe"])
    if word.endswith("ss"):
        return bases
    if word.endswith("s"):
        bases.append(word[:-1])
    if word.endswith("es"):
        bases.append(word[:-2])
    cleaned = []
    seen = set()
    for base in bases:
        if base and base != word and base.isalpha() and base not in seen:
            cleaned.append(base)
            seen.add(base)
    return cleaned


def possible_inflection_bases(word):
    bases = []
    if len(word) <= 4:
        return bases
    if word.endswith("ies") and len(word) > 4:
        bases.append(word[:-3] + "y")
    if word.endswith("ves") and len(word) > 4:
        bases.extend([word[:-3] + "f", word[:-3] + "fe"])
    if word.endswith("es") and len(word) > 4:
        bases.append(word[:-2])
    if word.endswith("s") and len(word) > 4 and word not in PLURAL_EXCEPTIONS:
        bases.append(word[:-1])
    if word.endswith("ied") and len(word) > 5:
        bases.append(word[:-3] + "y")
    if word.endswith("ed") and len(word) > 4:
        bases.extend([word[:-2], word[:-1]])
    if word.endswith("ing") and len(word) > 5:
        stem = word[:-3]
        bases.extend([stem, stem + "e"])
        if len(stem) >= 2 and stem[-1] == stem[-2]:
            bases.append(stem[:-1])
    if word.endswith("er") and len(word) > 4:
        bases.extend([word[:-2], word[:-1]])
        if word[:-2].endswith("i"):
            bases.append(word[:-3] + "y")
    if word.endswith("est") and len(word) > 5:
        bases.extend([word[:-3], word[:-2]])
        if word[:-3].endswith("i"):
            bases.append(word[:-4] + "y")

    cleaned = []
    seen = set()
    for base in bases:
        if base and base != word and base.isalpha() and base not in seen:
            cleaned.append(base)
            seen.add(base)
    return cleaned


def known_inflection_base(word, known_words, known_forms, known_form_bases):
    if word in known_forms and word not in known_words:
        return known_form_bases.get(word) or "known_form"
    for base in possible_inflection_bases(word):
        if base in known_words:
            return base
    return ""


def plural_canonical(word, counter, reference_words, min_count):
    for base in possible_plural_bases(word):
        if base in reference_words or counter.get(base, 0) >= min_count:
            return base
    return ""


def capitalization_ratios(cap_counter):
    total = sum(cap_counter.values()) or 1
    return {
        "all_caps_ratio": cap_counter["all_caps"] / total,
        "titlecase_ratio": cap_counter["title"] / total,
        "lowercase_ratio": cap_counter["lower"] / total,
        "mixedcase_ratio": cap_counter["mixed"] / total,
    }


def reject_reason(row, args):
    word = row["word"]
    if row["in_known"]:
        return "known"
    if row["known_inflection_base"]:
        return "inflection_of_known"
    if len(word) < args.min_length and word not in SHORT_ALLOWLIST:
        return "short_attention"
    if len(word) > args.max_length:
        return "too_long"
    if row["all_caps_ratio"] >= args.acronym_ratio and len(word) <= 10:
        return "acronym_like"
    if (row["titlecase_ratio"] + row["mixedcase_ratio"]) >= args.proper_ratio and row["lowercase_ratio"] < args.min_lowercase_ratio:
        return "proper_or_brand_like"
    if row["lowercase_ratio"] == 0 and (row["titlecase_ratio"] + row["mixedcase_ratio"] + row["all_caps_ratio"]) >= args.proper_ratio:
        return "proper_or_brand_like"
    if row["in_reference"]:
        if row["count"] < args.min_ecdict_count:
            return "low_count"
        if row["doc_count"] < args.min_ecdict_docs:
            return "low_doc_count"
    else:
        if row["count"] < args.min_non_ecdict_count:
            return "low_count"
        if row["doc_count"] < args.min_non_ecdict_docs:
            return "low_doc_count"
    return ""


def write_csv(path, rows, fieldnames):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_word_targets(path, words):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["word"])
        writer.writeheader()
        for word in words:
            writer.writerow({"word": word})


def parse_args():
    parser = argparse.ArgumentParser(description="Build a cleaned LessWrong-derived generation word list.")
    parser.add_argument("--corpus", type=Path, default=Path("/Users/haique/Downloads/lesswrong_full.json"))
    parser.add_argument("--known-words", type=Path, default=Path("data/generation-targets/oxford5000/words.csv"))
    parser.add_argument("--known-phrases", type=Path, default=Path("outputs/wordlist-builds/oxford5000/phrases.csv"))
    parser.add_argument("--known-wordforms", type=Path, default=Path("data/lemma-wordforms.csv"))
    parser.add_argument("--ecdict", type=Path, default=Path("vendor/ecdict/ecdict.csv"))
    parser.add_argument("--reference-words", type=Path, default=Path("data/ecdict-clean-words.csv"))
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/wordlist-builds/lesswrong"))
    parser.add_argument("--targets", type=Path, default=Path("data/generation-targets/lesswrong/words.csv"))
    parser.add_argument("--min-score", type=float, default=25)
    parser.add_argument("--min-ecdict-count", type=int, default=2)
    parser.add_argument("--min-ecdict-docs", type=int, default=2)
    parser.add_argument("--min-non-ecdict-count", type=int, default=20)
    parser.add_argument("--min-non-ecdict-docs", type=int, default=8)
    parser.add_argument("--min-length", type=int, default=4)
    parser.add_argument("--max-length", type=int, default=28)
    parser.add_argument("--acronym-ratio", type=float, default=0.75)
    parser.add_argument("--proper-ratio", type=float, default=0.85)
    parser.add_argument("--min-lowercase-ratio", type=float, default=0.15)
    parser.add_argument("--review-limit", type=int, default=300)
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
    cap_counters = defaultdict(Counter)
    reject_chunks = Counter()
    posts_total = 0
    posts_used = 0
    date_min = None
    date_max = None

    with args.corpus.open("r", encoding="utf-8") as f:
        posts = json.load(f)["data"]["posts"]["results"]

    posts_total = len(posts)
    for index, post in enumerate(posts, 1):
        score = post.get("baseScore") or 0
        posted_at = parse_date(post.get("postedAt"))
        if posted_at:
            date_min = posted_at if date_min is None else min(date_min, posted_at)
            date_max = posted_at if date_max is None else max(date_max, posted_at)
        if score < args.min_score:
            continue

        post_words = []
        for chunk in post_text(post).split():
            word, reason = clean_chunk(chunk)
            if reason:
                reject_chunks[reason] += 1
                continue
            post_words.append((word, chunk))

        if not post_words:
            continue

        posts_used += 1
        counter.update(word for word, _raw in post_words)
        doc_counter.update({word for word, _raw in post_words})
        for word, raw in post_words:
            cap_counters[word][cap_kind(raw)] += 1

        if index % 5000 == 0:
            print(f"processed={index}/{posts_total} used={posts_used}")

    raw_rows = []
    for word, count in counter.most_common():
        ratios = capitalization_ratios(cap_counters[word])
        known_base = known_inflection_base(word, known_words, known_forms, known_form_bases)
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
        row["reject_reason"] = reject_reason(row, args)
        raw_rows.append(row)

    canonical_rows = {}
    variants = defaultdict(list)
    for row in raw_rows:
        if row["reject_reason"]:
            continue
        canonical = row["plural_canonical"] or row["word"]
        if canonical in known_words:
            continue
        variants[canonical].append(row["word"])
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
    write_csv(
        args.output_dir / "short-attention.csv",
        [row for row in raw_rows if row["reject_reason"] == "short_attention"],
        detail_fields,
    )
    write_csv(
        args.output_dir / "proper-or-brand-like.csv",
        [row for row in raw_rows if row["reject_reason"] == "proper_or_brand_like"],
        detail_fields,
    )
    write_csv(
        args.output_dir / "acronym-like.csv",
        [row for row in raw_rows if row["reject_reason"] == "acronym_like"],
        detail_fields,
    )
    write_csv(args.output_dir / "manual-review-top.csv", candidates[: args.review_limit], candidate_fields)

    summary = {
        "corpus": str(args.corpus),
        "known_words": str(args.known_words),
        "posts_total": posts_total,
        "posts_used": posts_used,
        "min_score": args.min_score,
        "min_ecdict_count": args.min_ecdict_count,
        "min_ecdict_docs": args.min_ecdict_docs,
        "min_non_ecdict_count": args.min_non_ecdict_count,
        "min_non_ecdict_docs": args.min_non_ecdict_docs,
        "date_min": date_min.isoformat() if date_min else None,
        "date_max": date_max.isoformat() if date_max else None,
        "total_clean_alpha_tokens": sum(counter.values()),
        "unique_clean_alpha_tokens": len(counter),
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
        },
    }
    (args.output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
