#!/usr/bin/env python3
"""Build a cognitive-science academic candidate word source.

Harvests domain vocabulary for cognitive science and its neighboring fields
(neuroscience, psychology, computer science / AI, philosophy, linguistics,
anthropology) from curated public sources:

  - Wikipedia glossary/index pages (parsed wikitext: {{term}}, ;-lines, links)
  - Wiktionary topical categories (en:Neuroscience, en:Psychology, ...)
  - arXiv abstracts (cs.AI, cs.CL, cs.LG, q-bio.NC) by document frequency
  - Stanford Encyclopedia of Philosophy table of contents

Single-word tokens are merged with per-word provenance, then diffed against
the existing production candidate pool so the output contains only NEW
candidates. Multiword glossary terms are kept aside in phrases.csv for a
future decision; they do not enter words.csv.

Two phases, resumable (raw downloads are cached under --raw-dir):

  python3 -m deepdict.wordlists.build_cogsci_wordlist --fetch
  python3 -m deepdict.wordlists.build_cogsci_wordlist --build
"""

import argparse
import csv
import json
import re
import time
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

USER_AGENT = "DeepDict-lexicon-builder/0.1 (personal dictionary project)"

WIKIPEDIA_PAGES = {
    "neuroscience": ["Glossary of neuroscience"],
    "psychology": ["Glossary of psychiatry", "Index of psychology articles", "List of cognitive biases"],
    "cogsci": ["Index of cognitive science articles"],
    "ai": ["Glossary of artificial intelligence"],
    "cs": ["Glossary of computer science"],
    "philosophy": ["Glossary of philosophy", "Index of philosophy articles (A–C)"],
    "linguistics": ["Index of linguistics articles"],
    "statistics": ["Glossary of probability and statistics"],
}

WIKTIONARY_CATEGORIES = {
    "neuroscience": ["en:Neuroscience", "en:Neuroanatomy"],
    "psychology": ["en:Psychology", "en:Psychiatry", "en:Emotions"],
    "cogsci": ["en:Cognitive science", "en:Cognition"],
    "ai": ["en:Artificial intelligence", "en:Machine learning"],
    "cs": ["en:Computer science", "en:Programming"],
    "philosophy": ["en:Philosophy", "en:Epistemology", "en:Ethics", "en:Logic", "en:Metaphysics"],
    "linguistics": ["en:Linguistics", "en:Semantics", "en:Phonetics"],
    "anthropology": ["en:Anthropology"],
    "statistics": ["en:Statistics"],
}

ARXIV_CATEGORIES = {
    "ai": ["cs.AI", "cs.LG"],
    "linguistics": ["cs.CL"],
    "neuroscience": ["q-bio.NC"],
}

SEP_URL = "https://plato.stanford.edu/contents.html"

# wiki markup and LaTeX junk that survives tokenization
TOKEN_BLACKLIST = {
    "thumb", "px", "ref", "refn", "cite", "citation", "isbn", "doi", "pmid",
    "pmc", "url", "http", "https", "www", "jpg", "jpeg", "png", "svg", "gif",
    "file", "image", "category", "template", "wikipedia", "wiktionary",
    "glossary", "efn", "sfn", "frac", "mathbb", "mathcal", "mathrm", "mathbf",
    "ldots", "cdot", "cdots", "varepsilon", "infty", "sqrt", "tilde",
    "langle", "rangle", "leq", "geq", "neq", "sim", "approx", "propto",
    "et", "al", "etc", "eg", "ie",
}

TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z'’-]*")


def http_get(url, retries=3, sleep=3.0):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    last = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return response.read().decode("utf-8", errors="replace")
        except Exception as exc:
            last = exc
            time.sleep(sleep * (attempt + 1))
    raise last


def fetch_wikipedia(raw_dir):
    out_dir = raw_dir / "wikipedia"
    out_dir.mkdir(parents=True, exist_ok=True)
    for field, titles in WIKIPEDIA_PAGES.items():
        for title in titles:
            slug = re.sub(r"[^A-Za-z0-9]+", "_", title).strip("_")
            path = out_dir / f"{field}__{slug}.json"
            if path.exists():
                print(f"cached {title}")
                continue
            url = (
                "https://en.wikipedia.org/w/api.php?action=parse&prop=wikitext"
                "&format=json&formatversion=2&redirects=1&page="
                + urllib.parse.quote(title)
            )
            try:
                data = json.loads(http_get(url))
            except Exception as exc:
                print(f"FAILED {title}: {exc}")
                continue
            if "error" in data:
                print(f"missing page: {title} ({data['error'].get('code')})")
                continue
            path.write_text(json.dumps({
                "field": field,
                "title": title,
                "wikitext": data["parse"]["wikitext"],
            }, ensure_ascii=False), encoding="utf-8")
            print(f"fetched {title} ({len(data['parse']['wikitext'])} chars)")
            time.sleep(1.0)


def fetch_wiktionary(raw_dir):
    out_dir = raw_dir / "wiktionary"
    out_dir.mkdir(parents=True, exist_ok=True)
    for field, categories in WIKTIONARY_CATEGORIES.items():
        for category in categories:
            slug = re.sub(r"[^A-Za-z0-9]+", "_", category).strip("_")
            path = out_dir / f"{field}__{slug}.json"
            if path.exists():
                print(f"cached {category}")
                continue
            members = []
            cmcontinue = None
            try:
                while True:
                    url = (
                        "https://en.wiktionary.org/w/api.php?action=query"
                        "&list=categorymembers&cmtype=page&cmlimit=500&format=json"
                        "&cmtitle=" + urllib.parse.quote(f"Category:{category}")
                    )
                    if cmcontinue:
                        url += "&cmcontinue=" + urllib.parse.quote(cmcontinue)
                    data = json.loads(http_get(url))
                    members.extend(
                        m["title"] for m in data.get("query", {}).get("categorymembers", [])
                    )
                    cmcontinue = data.get("continue", {}).get("cmcontinue")
                    if not cmcontinue:
                        break
                    time.sleep(0.5)
            except Exception as exc:
                print(f"FAILED {category}: {exc}")
                continue
            path.write_text(json.dumps({
                "field": field,
                "category": category,
                "members": members,
            }, ensure_ascii=False), encoding="utf-8")
            print(f"fetched Category:{category}: {len(members)} members")
            time.sleep(0.5)


def fetch_arxiv(raw_dir, per_category=2000, page_size=1000):
    out_dir = raw_dir / "arxiv"
    out_dir.mkdir(parents=True, exist_ok=True)
    for field, categories in ARXIV_CATEGORIES.items():
        for category in categories:
            path = out_dir / f"{field}__{category.replace('.', '_')}.json"
            if path.exists():
                print(f"cached arxiv {category}")
                continue
            abstracts = []
            try:
                for start in range(0, per_category, page_size):
                    url = (
                        "http://export.arxiv.org/api/query?search_query="
                        + urllib.parse.quote(f"cat:{category}")
                        + f"&start={start}&max_results={page_size}"
                        "&sortBy=submittedDate&sortOrder=descending"
                    )
                    xml = http_get(url)
                    found = re.findall(r"<summary>(.*?)</summary>", xml, re.DOTALL)
                    abstracts.extend(found)
                    print(f"arxiv {category} start={start}: +{len(found)}")
                    if len(found) < page_size // 2:
                        break
                    time.sleep(3.0)
            except Exception as exc:
                print(f"FAILED arxiv {category}: {exc}")
                if not abstracts:
                    continue
            path.write_text(json.dumps({
                "field": field,
                "category": category,
                "abstracts": abstracts,
            }, ensure_ascii=False), encoding="utf-8")
            print(f"fetched arxiv {category}: {len(abstracts)} abstracts")


def fetch_sep(raw_dir):
    path = raw_dir / "sep_contents.json"
    if path.exists():
        print("cached SEP contents")
        return
    try:
        html = http_get(SEP_URL)
    except Exception as exc:
        print(f"FAILED SEP: {exc}")
        return
    titles = re.findall(r'href="entries/[^"]+"\s*>([^<]+)<', html)
    path.write_text(json.dumps({"field": "philosophy", "titles": titles}, ensure_ascii=False),
                    encoding="utf-8")
    print(f"fetched SEP contents: {len(titles)} entry titles")


def normalize_token(token):
    token = token.replace("’", "'").strip("'-")
    if token.endswith("'s"):
        token = token[:-2]
    return token


def tokens_from_text(text):
    for raw in TOKEN_RE.findall(text):
        token = normalize_token(raw)
        if len(token) < 3 or len(token) > 30:
            continue
        lower = token.lower()
        if lower in TOKEN_BLACKLIST:
            continue
        yield token, lower


def wikitext_terms(wikitext):
    """Extract term strings from glossary/index wikitext."""
    terms = []
    for match in re.finditer(r"\{\{term\|(?:1=)?([^|}]+)", wikitext):
        terms.append(match.group(1))
    for match in re.finditer(r"^;\s*(.+)$", wikitext, re.MULTILINE):
        terms.append(re.sub(r"\[\[(?:[^\]|]*\|)?([^\]|]+)\]\]", r"\1", match.group(1)))
    for match in re.finditer(r"\[\[([^\]|#]+)", wikitext):
        terms.append(match.group(1))
    return terms


def classify_tier(row, in_ecdict, zipf):
    """Grade a candidate by provenance, shape, and corroboration.

    The existing production pool is essentially single-token (only ~20
    hyphenated entries), so hyphenated compounds are held aside rather than
    fed to generation. arXiv-only words are the weakest provenance: kept, but
    in their own opt-in tier.

      core     - single token from a human-curated source (recommended input)
      compound - hyphenated (any source)
      arxiv    - single token seen only in arXiv abstracts
    """
    curated = any(s in row["sources"] for s in ("wikipedia", "wiktionary", "sep"))
    if "-" in row["word"]:
        return "compound"
    if not curated:
        return "arxiv"
    return "core"


def build(raw_dir, out_words, out_phrases, out_provenance, out_summary,
          pool_paths, min_arxiv_docs=3, ecdict_path=None):
    word_fields = defaultdict(set)   # lower word -> fields
    word_sources = defaultdict(set)  # lower word -> source kinds
    cap_counts = defaultdict(Counter)
    phrases = defaultdict(set)       # phrase -> fields

    def add_term_tokens(term, field, source):
        term = term.strip()
        if not term or term.startswith(("Category:", "File:", "Template:", "Wikipedia:", "Help:")):
            return
        toks = list(tokens_from_text(term))
        if not toks:
            return
        if len(toks) > 1 and 2 <= len(toks) <= 4 and source != "arxiv":
            phrase = " ".join(t for t, _ in toks).lower()
            phrases[phrase].add(field)
        for token, lower in toks:
            word_fields[lower].add(field)
            word_sources[lower].add(source)
            cap_counts[lower][token[0].isupper()] += 1

    for path in sorted((raw_dir / "wikipedia").glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        for term in wikitext_terms(data["wikitext"]):
            add_term_tokens(term, data["field"], "wikipedia")

    for path in sorted((raw_dir / "wiktionary").glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        for member in data["members"]:
            add_term_tokens(member, data["field"], "wiktionary")

    sep_path = raw_dir / "sep_contents.json"
    if sep_path.exists():
        data = json.loads(sep_path.read_text(encoding="utf-8"))
        for title in data["titles"]:
            add_term_tokens(title, "philosophy", "sep")

    # arXiv: document frequency over abstracts; lowercase evidence required so
    # proper names and sentence-initial capitals don't slip in via prose.
    for path in sorted((raw_dir / "arxiv").glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        doc_freq = Counter()
        lower_evidence = Counter()
        for abstract in data["abstracts"]:
            seen = set()
            for token, lower in tokens_from_text(abstract):
                if lower not in seen:
                    seen.add(lower)
                    doc_freq[lower] += 1
                if token == lower:
                    lower_evidence[lower] += 1
        for lower, df in doc_freq.items():
            if df >= min_arxiv_docs and lower_evidence[lower] >= min_arxiv_docs:
                word_fields[lower].add(data["field"])
                word_sources[lower].add("arxiv")
                cap_counts[lower][False] += df

    pool = set()
    for path in pool_paths:
        with Path(path).open("r", encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                word = (row.get("word") or "").strip().casefold()
                if word:
                    pool.add(word)

    # ECDICT membership + zipf frequency to grade candidates.
    ecdict_words = set()
    if ecdict_path and Path(ecdict_path).exists():
        import sys
        csv.field_size_limit(sys.maxsize)
        with Path(ecdict_path).open("r", encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                w = (row.get("word") or "").strip().lower()
                if w:
                    ecdict_words.add(w)
    try:
        from wordfreq import zipf_frequency
    except ImportError:
        zipf_frequency = None

    rows = []
    for lower in sorted(word_fields):
        if lower in pool:
            continue
        if not re.fullmatch(r"[a-z][a-z'-]*[a-z]", lower):
            continue
        caps = cap_counts[lower]
        cap_ratio = caps[True] / max(1, caps[True] + caps[False])
        in_ecdict = lower in ecdict_words
        zipf = round(zipf_frequency(lower, "en"), 2) if zipf_frequency else ""
        row = {
            "word": lower,
            "fields": "|".join(sorted(word_fields[lower])),
            "sources": "|".join(sorted(word_sources[lower])),
            "n_fields": len(word_fields[lower]),
            "n_sources": len(word_sources[lower]),
            "cap_ratio": round(cap_ratio, 2),
            "in_ecdict": int(in_ecdict),
            "zipf": zipf,
        }
        row["tier"] = classify_tier(row, in_ecdict, zipf)
        rows.append(row)

    rows.sort(key=lambda r: (-r["n_sources"], -r["n_fields"], r["word"]))

    by_tier = defaultdict(list)
    for row in rows:
        by_tier[row["tier"]].append(row)

    # words.csv = recommended core tier; other tiers in opt-in files.
    out_words.parent.mkdir(parents=True, exist_ok=True)
    with out_words.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["word"])
        writer.writeheader()
        for row in by_tier["core"]:
            writer.writerow({"word": row["word"]})

    for tier in ("compound", "arxiv"):
        path = out_words.parent / f"words-{tier}.csv"
        with path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["word"])
            writer.writeheader()
            for row in by_tier[tier]:
                writer.writerow({"word": row["word"]})

    out_provenance.parent.mkdir(parents=True, exist_ok=True)
    with out_provenance.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["word", "tier", "fields", "sources", "n_fields",
                        "n_sources", "cap_ratio", "in_ecdict", "zipf"],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    new_phrases = sorted(p for p in phrases if p.casefold() not in pool)
    with out_phrases.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["phrase", "fields"])
        writer.writeheader()
        for phrase in new_phrases:
            writer.writerow({"phrase": phrase, "fields": "|".join(sorted(phrases[phrase]))})

    field_counts = Counter()
    for row in by_tier["core"]:
        for field in row["fields"].split("|"):
            field_counts[field] += 1
    summary = {
        "candidate_words_total": len(rows),
        "core_tier_words": len(by_tier["core"]),
        "compound_tier_words": len(by_tier["compound"]),
        "arxiv_tier_words": len(by_tier["arxiv"]),
        "core_in_ecdict": sum(r["in_ecdict"] for r in by_tier["core"]),
        "core_rare_not_in_ecdict": sum(1 for r in by_tier["core"] if not r["in_ecdict"]),
        "harvested_unique_tokens": len(word_fields),
        "already_in_pool": len(word_fields) - len(rows),
        "phrases_kept_aside": len(new_phrases),
        "by_field": dict(sorted(field_counts.items())),
        "by_source": dict(Counter(
            s for row in rows for s in row["sources"].split("|")
        )),
    }
    out_summary.parent.mkdir(parents=True, exist_ok=True)
    out_summary.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"words={out_words}")
    print(f"provenance={out_provenance}")
    print(f"phrases={out_phrases}")


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fetch", action="store_true", help="Download raw sources (cached).")
    parser.add_argument("--build", action="store_true", help="Build the candidate table from raw cache.")
    parser.add_argument("--raw-dir", type=Path, default=Path("work/cogsci-raw"))
    parser.add_argument("--arxiv-per-category", type=int, default=2000)
    parser.add_argument("--min-arxiv-docs", type=int, default=3)
    parser.add_argument(
        "--pool",
        type=Path,
        action="append",
        default=[],
        help="Existing word CSVs to diff against. Defaults to the production candidate pool.",
    )
    parser.add_argument("--ecdict", type=Path, default=Path("vendor/ecdict/ecdict.csv"))
    parser.add_argument("--out-dir", type=Path, default=Path("data/generation-targets/cogsci-academic"))
    parser.add_argument("--summary-dir", type=Path, default=Path("outputs/wordlist-builds/cogsci-academic"))
    return parser.parse_args()


def main():
    args = parse_args()
    if not args.fetch and not args.build:
        print("nothing to do: pass --fetch and/or --build")
        return 1
    if args.fetch:
        fetch_wikipedia(args.raw_dir)
        fetch_wiktionary(args.raw_dir)
        fetch_arxiv(args.raw_dir, per_category=args.arxiv_per_category)
        fetch_sep(args.raw_dir)
    if args.build:
        pool_paths = args.pool or [Path("data/generation-targets/merged-clean/words.csv")]
        build(
            args.raw_dir,
            out_words=args.out_dir / "words.csv",
            out_phrases=args.out_dir / "phrases.csv",
            out_provenance=args.out_dir / "provenance.csv",
            out_summary=args.summary_dir / "summary.json",
            pool_paths=pool_paths,
            min_arxiv_docs=args.min_arxiv_docs,
            ecdict_path=args.ecdict,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
