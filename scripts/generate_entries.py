#!/usr/bin/env python3
import argparse
import csv
import hashlib
import json
import os
import random
import re
import sys
import tempfile
import time
import unicodedata
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-v4-pro"
POS_VALUES = {
    "n.",
    "v.",
    "adj.",
    "adv.",
    "prep.",
    "pron.",
    "conj.",
    "interj.",
    "det.",
    "num.",
    "aux.",
    "modal",
    "prefix",
    "suffix",
}
POS_ALIASES = {
    "abbr.": "n.",
    "abbrev.": "n.",
    "abbreviation": "n.",
    "noun": "n.",
    "verb": "v.",
    "adjective": "adj.",
    "adverb": "adv.",
    "preposition": "prep.",
    "pronoun": "pron.",
    "conjunction": "conj.",
    "interjection": "interj.",
    "determiner": "det.",
    "number": "num.",
    "particle": "prep.",
    "infinitive marker": "prep.",
    "article": "det.",
    "art.": "det.",
    "contraction": "interj.",
    "phrase": "interj.",
}
EXCLUDE_REASONS = {
    "not_english_word",
    "misspelling_or_fragment",
    "nonstandard_contraction_spelling",
    "abbreviation_or_acronym",
    "proper_name_or_brand",
    "username_or_platform_artifact",
    "profanity_or_slur",
    "too_uncertain",
    "not_useful_for_reading",
}


def stable_id(word):
    normalized = unicodedata.normalize("NFKD", word)
    ascii_word = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    slug = re.sub(r"[^A-Za-z0-9]+", "_", ascii_word).strip("_").lower()
    if not slug:
        digest = hashlib.sha1(word.encode("utf-8")).hexdigest()[:10]
        slug = f"x_{digest}"
    return f"w_{slug}"


def load_words(path, offset, limit):
    words = []
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if "word" not in (reader.fieldnames or []):
            raise ValueError(f"{path} must contain a 'word' column")
        for row in reader:
            word = (row.get("word") or "").strip()
            if word:
                words.append(word)

    if offset:
        words = words[offset:]
    if limit is not None:
        words = words[:limit]
    return words


def load_word_set(path):
    words = set()
    if not path.exists():
        return words
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if "word" not in (reader.fieldnames or []):
            raise ValueError(f"{path} must contain a 'word' column")
        for row in reader:
            word = (row.get("word") or "").strip().lower()
            if word:
                words.add(word)
    return words


def load_protected_words(paths):
    protected = set()
    for path in paths:
        protected.update(load_word_set(path))
    return protected


def load_prompt(path):
    return path.read_text(encoding="utf-8").strip()


def build_user_prompt(word):
    return (
        "请为下面这个英文词生成词典义项。\n\n"
        f"输入词：{word}\n\n"
        "只输出符合要求的 JSON object。"
    )


def post_json(url, api_key, payload, timeout):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def call_model(word, system_prompt, args, api_key):
    base_url = args.base_url.rstrip("/")
    url = f"{base_url}/chat/completions"
    payload = {
        "model": args.model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": build_user_prompt(word)},
        ],
        "response_format": {"type": "json_object"},
        "temperature": args.temperature,
        "max_tokens": args.max_tokens,
    }
    if args.thinking != "auto":
        payload["thinking"] = {"type": args.thinking}
    if args.reasoning_effort != "auto":
        payload["reasoning_effort"] = args.reasoning_effort

    response = post_json(url, api_key, payload, args.timeout)
    try:
        choice = response["choices"][0]
        finish_reason = choice.get("finish_reason")
        content = choice["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError(f"unexpected API response shape: {response!r}") from exc

    if finish_reason == "length":
        raise ValueError("model output was truncated")
    if not content:
        raise ValueError("empty model output")

    try:
        data = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError(f"model did not return valid JSON: {content[:500]!r}") from exc

    return data, response.get("usage", {})


def validate_score(data, key):
    value = data.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{key} must be an integer")
    if value < 0 or value > 10:
        raise ValueError(f"{key} must be between 0 and 10")
    return value


def validate_entry(data, expected_word, protected_words=frozenset()):
    if not isinstance(data, dict):
        raise ValueError("entry must be a JSON object")
    if data.get("word") != expected_word:
        raise ValueError(f"word mismatch: expected {expected_word!r}, got {data.get('word')!r}")
    include = data.get("include")
    if not isinstance(include, bool):
        raise ValueError("include must be a boolean")
    suitability_score = validate_score(data, "suitability_score")
    meaning_confidence = validate_score(data, "meaning_confidence")
    exclude_reason = data.get("exclude_reason")

    senses = data.get("senses")
    if not isinstance(senses, list):
        raise ValueError("senses must be an array")

    allowed_entry_keys = {
        "word",
        "include",
        "suitability_score",
        "meaning_confidence",
        "exclude_reason",
        "senses",
    }
    extra_entry_keys = set(data) - allowed_entry_keys
    if extra_entry_keys:
        raise ValueError(f"unexpected entry keys: {sorted(extra_entry_keys)}")

    if include:
        if exclude_reason is not None:
            raise ValueError("exclude_reason must be null when include is true")
        if meaning_confidence <= 4:
            raise ValueError("include=true requires meaning_confidence > 4")
        if not senses:
            raise ValueError("senses must be a non-empty array when include is true")
    else:
        if expected_word.lower() in protected_words:
            raise ValueError(f"protected word was excluded: {expected_word}")
        if exclude_reason not in EXCLUDE_REASONS:
            raise ValueError(f"invalid exclude_reason: {exclude_reason!r}")
        if senses:
            raise ValueError("senses must be empty when include is false")
        return {
            "word": data["word"],
            "include": False,
            "suitability_score": suitability_score,
            "meaning_confidence": meaning_confidence,
            "exclude_reason": exclude_reason,
            "senses": [],
        }

    required_sense_keys = {"pos", "context_label", "gloss_zh"}
    optional_sense_keys = {"definition_zh"}
    allowed_sense_keys = required_sense_keys | optional_sense_keys
    for idx, sense in enumerate(senses, 1):
        if not isinstance(sense, dict):
            raise ValueError(f"sense {idx} must be an object")
        keys = set(sense)
        missing = required_sense_keys - keys
        extra = keys - allowed_sense_keys
        if missing:
            raise ValueError(f"sense {idx} missing keys: {sorted(missing)}")
        if extra:
            raise ValueError(f"sense {idx} has unexpected keys: {sorted(extra)}")

        pos = str(sense["pos"]).strip()
        pos = POS_ALIASES.get(pos.lower(), pos)
        if pos not in POS_VALUES:
            raise ValueError(f"sense {idx} has invalid pos: {pos!r}")
        sense["pos"] = pos

        context_label = sense["context_label"]
        if not isinstance(context_label, str):
            raise ValueError(f"sense {idx} context_label must be a string")
        if context_label.count("/") >= 3:
            raise ValueError(f"sense {idx} context_label has too many labels")

        value = sense["gloss_zh"]
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"sense {idx} gloss_zh must be a non-empty string")

        if "definition_zh" in sense and not isinstance(sense["definition_zh"], str):
            raise ValueError(f"sense {idx} definition_zh must be a string")

    return {
        "word": data["word"],
        "include": True,
        "suitability_score": suitability_score,
        "meaning_confidence": meaning_confidence,
        "exclude_reason": None,
        "senses": [
            ({
                "pos": sense["pos"].strip(),
                "context_label": sense["context_label"].strip(),
                "gloss_zh": sense["gloss_zh"].strip(),
            } | (
                {"definition_zh": sense["definition_zh"].strip()}
                if "definition_zh" in sense and sense["definition_zh"].strip()
                else {}
            ))
            for sense in senses
        ],
    }


def write_json_atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=str(path.parent),
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as f:
        tmp_path = Path(f.name)
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    tmp_path.replace(path)


def add_usage(total, usage):
    if not isinstance(usage, dict):
        return
    for key, value in usage.items():
        if isinstance(value, (int, float)):
            total[key] = total.get(key, 0) + value
        elif isinstance(value, dict):
            nested = total.setdefault(key, {})
            add_usage(nested, value)


def error_payload(word, attempt, exc):
    return {
        "word": word,
        "attempt": attempt,
        "error_type": type(exc).__name__,
        "error": str(exc),
    }


def generate_one(word, system_prompt, args, api_key, protected_words):
    entry_id = stable_id(word)
    output_path = args.output_dir / f"{entry_id}.json"
    error_path = args.error_dir / f"{entry_id}.json"

    if output_path.exists() and not args.overwrite:
        try:
            existing = json.loads(output_path.read_text(encoding="utf-8"))
            cleaned = validate_entry(existing, word, protected_words)
            if error_path.exists():
                error_path.unlink()
            if not cleaned["include"]:
                return "excluded", word, str(output_path), {}
            return "skipped", word, str(output_path), {}
        except Exception:
            output_path.unlink(missing_ok=True)
            pass

    last_error = None
    last_usage = {}
    for attempt in range(1, args.retries + 2):
        try:
            data, usage = call_model(word, system_prompt, args, api_key)
            last_usage = usage
            cleaned = validate_entry(data, word, protected_words)
            write_json_atomic(output_path, cleaned)
            if error_path.exists():
                error_path.unlink()
            if not cleaned["include"]:
                return "excluded", word, str(output_path), usage
            return "ok", word, str(output_path), usage
        except Exception as exc:
            last_error = exc
            if attempt <= args.retries:
                sleep_seconds = min(args.retry_max_sleep, args.retry_base_sleep * (2 ** (attempt - 1)))
                sleep_seconds += random.uniform(0, args.retry_jitter)
                time.sleep(sleep_seconds)

    payload = error_payload(word, args.retries + 1, last_error)
    if last_usage:
        payload["usage"] = last_usage
    write_json_atomic(error_path, payload)
    return "failed", word, str(error_path), last_usage


def parse_args():
    parser = argparse.ArgumentParser(
        description="Generate minimal dictionary entry JSON files with a DeepSeek-compatible chat API."
    )
    parser.add_argument("--input", default="data/generation-targets/merged-clean/words.csv", type=Path)
    parser.add_argument("--prompt", default="prompts/entry-generation-system.md", type=Path)
    parser.add_argument(
        "--protected-word-file",
        action="append",
        default=[],
        type=Path,
        help="CSV files with a word column. These words cannot be excluded by the model.",
    )
    parser.add_argument("--output-dir", default="outputs/entries-merged-clean", type=Path)
    parser.add_argument("--error-dir", default="outputs/errors-merged-clean", type=Path)
    parser.add_argument("--run-summary-dir", default="outputs/runs-merged-clean", type=Path)
    parser.add_argument("--base-url", default=os.environ.get("DEEPSEEK_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--model", default=os.environ.get("DEEPSEEK_MODEL", DEFAULT_MODEL))
    parser.add_argument("--api-key-env", default="DEEPSEEK_API_KEY")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--temperature", type=float, default=0.1)
    parser.add_argument("--max-tokens", type=int, default=1200)
    parser.add_argument("--timeout", type=float, default=60)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--retry-base-sleep", type=float, default=1.0)
    parser.add_argument("--retry-max-sleep", type=float, default=20.0)
    parser.add_argument("--retry-jitter", type=float, default=0.5)
    parser.add_argument(
        "--thinking",
        choices=["auto", "enabled", "disabled"],
        default="disabled",
        help="DeepSeek thinking mode. Use auto to omit the field.",
    )
    parser.add_argument(
        "--reasoning-effort",
        choices=["auto", "low", "high", "max"],
        default="auto",
        help="DeepSeek reasoning effort. Only meaningful when thinking is enabled.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    words = load_words(args.input, args.offset, args.limit)
    system_prompt = load_prompt(args.prompt)
    protected_words = load_protected_words(args.protected_word_file)

    print(f"input={args.input}")
    print(f"words={len(words)} offset={args.offset} limit={args.limit}")
    print(f"output_dir={args.output_dir}")
    print(f"error_dir={args.error_dir}")
    print(f"run_summary_dir={args.run_summary_dir}")
    print(f"base_url={args.base_url}")
    print(f"model={args.model}")
    print(f"thinking={args.thinking}")
    print(f"reasoning_effort={args.reasoning_effort}")
    print(f"workers={args.workers}")
    print(f"protected_words={len(protected_words)}")

    if args.dry_run:
        for word in words[:10]:
            print(stable_id(word), word)
        return 0

    api_key = os.environ.get(args.api_key_env)
    if not api_key:
        print(f"Missing API key env var: {args.api_key_env}", file=sys.stderr)
        return 2

    args.output_dir.mkdir(parents=True, exist_ok=True)
    args.error_dir.mkdir(parents=True, exist_ok=True)
    args.run_summary_dir.mkdir(parents=True, exist_ok=True)

    counts = {"ok": 0, "excluded": 0, "skipped": 0, "failed": 0}
    usage_total = {}
    started_at = datetime.now(timezone.utc)
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(generate_one, word, system_prompt, args, api_key, protected_words): word
            for word in words
        }
        for future in as_completed(futures):
            status, word, path, usage = future.result()
            counts[status] += 1
            add_usage(usage_total, usage)
            done = sum(counts.values())
            print(f"[{done}/{len(words)}] {status} {word} -> {path}", flush=True)

    finished_at = datetime.now(timezone.utc)
    summary = {
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "duration_seconds": round((finished_at - started_at).total_seconds(), 3),
        "input": str(args.input),
        "offset": args.offset,
        "limit": args.limit,
        "model": args.model,
        "base_url": args.base_url,
        "thinking": args.thinking,
        "reasoning_effort": args.reasoning_effort,
        "workers": args.workers,
        "protected_word_files": [str(path) for path in args.protected_word_file],
        "protected_words": len(protected_words),
        "counts": counts,
        "usage": usage_total,
    }
    run_id = finished_at.strftime("%Y%m%dT%H%M%SZ")
    summary_path = args.run_summary_dir / f"{run_id}.json"
    write_json_atomic(summary_path, summary)
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    print(f"run_summary={summary_path}")
    return 1 if counts["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
