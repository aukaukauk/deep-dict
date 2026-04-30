#!/usr/bin/env python3
import argparse
import csv
import json
import re
from collections import Counter
from pathlib import Path


SHORT_ALLOWLIST = {
    "a",
    "am",
    "an",
    "as",
    "at",
    "be",
    "by",
    "do",
    "go",
    "he",
    "hi",
    "i",
    "if",
    "in",
    "is",
    "it",
    "me",
    "my",
    "no",
    "of",
    "oh",
    "on",
    "or",
    "ox",
    "so",
    "to",
    "up",
    "us",
    "we",
}

POS_RE = re.compile(
    r"(^|[\s\r\n])("
    r"a|adj|adv|art|conj|det|interj|int|n|num|prep|pron|v|vi|vt"
    r")\.",
    re.IGNORECASE,
)
TRIPLE_REPEATED_RE = re.compile(r"([a-z])\1\1")

ABBREV_MARKERS = (
    "abbr",
    "缩写",
    "缩略",
    "的缩略",
    "缩略语",
)

PROPER_MARKERS = (
    "人名",
    "男子名",
    "女子名",
    "姓氏",
    "地名",
    "城市",
    "城镇",
    "首都",
    "港口",
    "州",
    "郡",
    "县",
    "省",
    "王朝",
    "公司名",
    "自治地区",
)

INFLECTION_MARKERS = (
    "的现在分词",
    "的过去式",
    "的过去分词",
    "的复数",
    "复数形式",
    "第三人称单数",
)

NOISE_PREFIXES = (
    "[计]",
    "[医]",
    "[军]",
    "[化]",
    "[经]",
    "[法]",
    "[网络]",
)


def parse_int(value):
    try:
        return int(value or 0)
    except ValueError:
        return 0


def has_common_pos(row):
    text = "\n".join([row.get("definition") or "", row.get("translation") or "", row.get("pos") or ""])
    return bool(POS_RE.search(text))


def marker_in(text, markers):
    folded = text.casefold()
    return any(marker.casefold() in folded for marker in markers)


def starts_with_noise_prefix(text):
    stripped = text.strip()
    return any(stripped.startswith(prefix) for prefix in NOISE_PREFIXES)


def looks_inflection_only(row, text):
    if not marker_in(text, INFLECTION_MARKERS):
        return False
    if parse_int(row.get("collins")) > 0 or (row.get("oxford") or "").strip():
        return False
    if re.search(r"(^|[\s\r\n])a\.", text):
        return False
    return True


def evidence(row):
    bnc = parse_int(row.get("bnc"))
    frq = parse_int(row.get("frq"))
    collins = parse_int(row.get("collins"))
    oxford = bool((row.get("oxford") or "").strip())
    tag = (row.get("tag") or "").strip()

    values = []
    if bnc > 0:
        values.append("bnc")
    if frq > 0:
        values.append("frq")
    if collins > 0:
        values.append("collins")
    if oxford:
        values.append("oxford")
    if tag:
        values.append("tag")
    return values


def reject_reason(row):
    source_word = (row.get("word") or "").strip()
    word = source_word.casefold()
    text = "\n".join([row.get("definition") or "", row.get("translation") or ""])
    ev = evidence(row)
    common_pos = has_common_pos(row)

    if not source_word or not source_word.isalpha():
        return "non_alpha"
    has_tag = bool((row.get("tag") or "").strip())
    has_strong_general_evidence = common_pos and (has_tag or parse_int(row.get("collins")) > 0 or (row.get("oxford") or "").strip())

    if source_word != source_word.lower():
        if source_word.casefold() in SHORT_ALLOWLIST and has_strong_general_evidence:
            pass
        elif source_word.isupper() and not has_strong_general_evidence:
            return "non_lowercase_or_acronym"
        elif not has_strong_general_evidence:
            return "non_lowercase_or_acronym"
    if len(word) > 24:
        return "too_long"
    if len(word) <= 2 and word not in SHORT_ALLOWLIST:
        return "short_code"
    if not ev:
        return "no_evidence"
    if marker_in(text, PROPER_MARKERS) and not has_strong_general_evidence:
        return "proper_name"
    if looks_inflection_only(row, text):
        return "inflection_only"
    if marker_in(text, ABBREV_MARKERS) and not common_pos:
        return "abbreviation"
    if starts_with_noise_prefix(row.get("translation") or "") and not common_pos and not (row.get("tag") or "").strip():
        return "domain_code_only"
    if len(word) <= 5 and marker_in(text, ABBREV_MARKERS) and not (row.get("tag") or "").strip():
        return "short_abbreviation"
    if TRIPLE_REPEATED_RE.search(word) and not ((row.get("tag") or "").strip() or parse_int(row.get("collins"))):
        return "repeated_noise"
    return ""


def row_score(row):
    score = 0
    bnc = parse_int(row.get("bnc"))
    frq = parse_int(row.get("frq"))
    collins = parse_int(row.get("collins"))
    if bnc > 0:
        score += max(1, 50000 - bnc)
    if frq > 0:
        score += max(1, 50000 - frq)
    score += collins * 100000
    if (row.get("oxford") or "").strip():
        score += 300000
    if (row.get("tag") or "").strip():
        score += 200000
    if has_common_pos(row):
        score += 10000
    return score


def load_current_words(path):
    words = set()
    with path.open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            word = (row.get("word") or "").strip()
            if word:
                words.add(word.casefold())
    return words


def choose_best_rows(rows):
    best = {}
    for row in rows:
        word = row["word"].casefold()
        if word not in best or row_score(row) > row_score(best[word]):
            best[word] = row
    return best


def write_words(path, words):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["word"])
        writer.writeheader()
        for word in sorted(words):
            writer.writerow({"word": word})


def write_candidate_details(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "word",
        "source_word",
        "bnc",
        "frq",
        "collins",
        "oxford",
        "tag",
        "translation",
        "exchange",
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "word": row["word"].casefold(),
                    "source_word": row["word"],
                    "bnc": row.get("bnc") or "",
                    "frq": row.get("frq") or "",
                    "collins": row.get("collins") or "",
                    "oxford": row.get("oxford") or "",
                    "tag": row.get("tag") or "",
                    "translation": (row.get("translation") or "").replace("\r\n", "\\n").replace("\n", "\\n"),
                    "exchange": row.get("exchange") or "",
                }
            )


def write_rejected_sample(path, rejected, limit):
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["word", "reason", "bnc", "frq", "collins", "oxford", "tag", "translation"]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row, reason in rejected[:limit]:
            writer.writerow(
                {
                    "word": row.get("word") or "",
                    "reason": reason,
                    "bnc": row.get("bnc") or "",
                    "frq": row.get("frq") or "",
                    "collins": row.get("collins") or "",
                    "oxford": row.get("oxford") or "",
                    "tag": row.get("tag") or "",
                    "translation": (row.get("translation") or "").replace("\r\n", "\\n").replace("\n", "\\n"),
                }
            )


def parse_args():
    parser = argparse.ArgumentParser(description="Filter ECDICT headwords into a cleaner main-dictionary supplement.")
    parser.add_argument("--ecdict", type=Path, default=Path("vendor/ecdict/ecdict.csv"))
    parser.add_argument("--current-words", type=Path, default=Path("data/lemma-words.csv"))
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/ecdict-filter"))
    parser.add_argument("--clean-all", type=Path, default=Path("data/ecdict-clean-words.csv"))
    parser.add_argument("--clean-new", type=Path, default=Path("data/ecdict-clean-new-words.csv"))
    parser.add_argument("--rejected-sample-limit", type=int, default=2000)
    return parser.parse_args()


def main():
    args = parse_args()
    current_words = load_current_words(args.current_words)
    rows = []
    rejected = []
    reject_counts = Counter()
    alpha_rows = 0

    with args.ecdict.open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            source_word = (row.get("word") or "").strip()
            if source_word and source_word.isalpha():
                alpha_rows += 1
            reason = reject_reason(row)
            if reason:
                reject_counts[reason] += 1
                if source_word and source_word.isalpha():
                    rejected.append((row, reason))
                continue
            rows.append(row)

    best = choose_best_rows(rows)
    clean_words = set(best)
    clean_new = clean_words - current_words
    overlap = clean_words & current_words

    write_words(args.clean_all, clean_words)
    write_words(args.clean_new, clean_new)
    write_candidate_details(args.output_dir / "clean-candidates.csv", [best[word] for word in sorted(clean_words)])
    write_candidate_details(args.output_dir / "clean-new-candidates.csv", [best[word] for word in sorted(clean_new)])
    write_rejected_sample(args.output_dir / "rejected-sample.csv", rejected, args.rejected_sample_limit)

    summary = {
        "ecdict": str(args.ecdict),
        "current_words": str(args.current_words),
        "alpha_rows": alpha_rows,
        "clean_words": len(clean_words),
        "current_word_count": len(current_words),
        "overlap_with_current": len(overlap),
        "new_clean_words": len(clean_new),
        "reject_counts": dict(reject_counts.most_common()),
        "outputs": {
            "clean_all": str(args.clean_all),
            "clean_new": str(args.clean_new),
            "clean_candidates": str(args.output_dir / "clean-candidates.csv"),
            "clean_new_candidates": str(args.output_dir / "clean-new-candidates.csv"),
            "rejected_sample": str(args.output_dir / "rejected-sample.csv"),
        },
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
