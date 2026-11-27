#!/usr/bin/env python3
import argparse
import csv
import json
import re
import urllib.request
from collections import defaultdict
from html.parser import HTMLParser
from pathlib import Path


DEFAULT_URL = "https://www.oxfordlearnersdictionaries.com/us/wordlists/oxford3000-5000"
WORD_RE = re.compile(r"^[a-z]+(?:-[a-z]+)*$")
LEVEL_ORDER = {"a1": 1, "a2": 2, "b1": 3, "b2": 4, "c1": 5, "c2": 6}


class OxfordWordlistParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows = []
        self.current = None
        self.in_pos = False

    def handle_starttag(self, tag, attrs):
        attr = dict(attrs)
        if tag == "li" and attr.get("data-hw") and attr.get("data-ox5000"):
            self.current = {
                "word": attr["data-hw"].strip(),
                "oxford3000": attr.get("data-ox3000", "").strip(),
                "oxford5000": attr.get("data-ox5000", "").strip(),
                "pos": "",
                "url": "",
            }
            return
        if not self.current:
            return
        if tag == "a" and not self.current["url"]:
            href = attr.get("href", "").strip()
            if href:
                self.current["url"] = href
        if tag == "span" and "pos" in (attr.get("class") or "").split():
            self.in_pos = True

    def handle_data(self, data):
        if self.current and self.in_pos:
            self.current["pos"] += data.strip()

    def handle_endtag(self, tag):
        if tag == "span" and self.in_pos:
            self.in_pos = False
        if tag == "li" and self.current:
            self.rows.append(self.current)
            self.current = None
            self.in_pos = False


def fetch_html(url):
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X) dictionary-wordlist-builder/0.1"
        },
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read().decode("utf-8", errors="replace")


def source_rows(html):
    parser = OxfordWordlistParser()
    parser.feed(html)
    rows = []
    seen = set()
    for row in parser.rows:
        word = row["word"].strip()
        pos = row["pos"].strip()
        cefr = row["oxford5000"].strip().lower()
        url = row["url"].strip()
        if url.startswith("/"):
            url = "https://www.oxfordlearnersdictionaries.com" + url
        key = (word.casefold(), pos.casefold(), cefr, url)
        if not word or key in seen:
            continue
        seen.add(key)
        rows.append(
            {
                "word": word.casefold(),
                "source_word": word,
                "pos": pos,
                "cefr": cefr,
                "in_oxford3000": "yes" if row["oxford3000"] else "no",
                "source_url": url,
            }
        )
    return rows


def min_level(levels):
    valid = [level for level in levels if level in LEVEL_ORDER]
    if not valid:
        return ""
    return min(valid, key=lambda item: LEVEL_ORDER[item])


def target_status(word):
    if " " in word:
        return "phrase"
    if not WORD_RE.match(word):
        return "non_word"
    return "include"


def build_targets(rows):
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["word"]].append(row)

    targets = []
    phrases = []
    excluded = []

    for word in sorted(grouped):
        items = grouped[word]
        levels = sorted({item["cefr"] for item in items}, key=lambda item: LEVEL_ORDER.get(item, 99))
        poses = sorted({item["pos"] for item in items if item["pos"]})
        in_3000 = any(item["in_oxford3000"] == "yes" for item in items)
        row = {
            "word": word,
            "cefr_min": min_level(levels),
            "cefr_levels": "|".join(levels),
            "pos": "|".join(poses),
            "in_oxford3000": "yes" if in_3000 else "no",
            "source_row_count": len(items),
            "include_for_generation": "yes",
            "exclude_reason": "",
        }
        status = target_status(word)
        if status == "include":
            targets.append(row)
        elif status == "phrase":
            row["include_for_generation"] = "no"
            row["exclude_reason"] = "phrase"
            phrases.append(row)
        else:
            row["include_for_generation"] = "no"
            row["exclude_reason"] = status
            excluded.append(row)
    return targets, phrases, excluded


def write_csv(path, rows, fieldnames):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def parse_args():
    parser = argparse.ArgumentParser(description="Extract clean Oxford 5000 core word tables.")
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--html", type=Path, help="Use an already downloaded Oxford wordlist HTML file.")
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/wordlist-builds/oxford5000"))
    parser.add_argument("--source-csv", type=Path, default=Path("outputs/wordlist-builds/oxford5000/source.csv"))
    parser.add_argument("--targets-csv", type=Path, default=Path("data/generation-targets/oxford5000/words.csv"))
    parser.add_argument("--phrases-csv", type=Path, default=Path("outputs/wordlist-builds/oxford5000/phrases.csv"))
    parser.add_argument("--excluded-csv", type=Path, default=Path("outputs/wordlist-builds/oxford5000/excluded.csv"))
    return parser.parse_args()


def main():
    args = parse_args()
    html = args.html.read_text(encoding="utf-8") if args.html else fetch_html(args.url)
    rows = source_rows(html)
    targets, phrases, excluded = build_targets(rows)

    source_fields = ["word", "source_word", "pos", "cefr", "in_oxford3000", "source_url"]
    target_fields = [
        "word",
        "cefr_min",
        "cefr_levels",
        "pos",
        "in_oxford3000",
        "source_row_count",
        "include_for_generation",
        "exclude_reason",
    ]
    write_csv(args.source_csv, rows, source_fields)
    write_csv(args.targets_csv, targets, target_fields)
    write_csv(args.phrases_csv, phrases, target_fields)
    write_csv(args.excluded_csv, excluded, target_fields)

    summary = {
        "source_url": args.url,
        "source_rows": len(rows),
        "unique_targets": len(targets),
        "phrases": len(phrases),
        "excluded_non_words": len(excluded),
        "oxford3000_targets": sum(1 for row in targets if row["in_oxford3000"] == "yes"),
        "oxford5000_only_targets": sum(1 for row in targets if row["in_oxford3000"] == "no"),
        "note": "Targets are de-duplicated headwords only. No plural or inflection expansion is added.",
        "outputs": {
            "source_csv": str(args.source_csv),
            "targets_csv": str(args.targets_csv),
            "phrases_csv": str(args.phrases_csv),
            "excluded_csv": str(args.excluded_csv),
        },
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
