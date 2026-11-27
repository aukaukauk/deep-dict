#!/usr/bin/env python3
"""Generate entries for the A/B word set with a given backend + the v2 prompt.

One stateless chat call per word (concurrent), validated against the
production schema, collected into a JSON array that ab_compare can read.
Backend is whatever ChatClient.from_env resolves (DeepSeek by default; point
base_url/model elsewhere for an OpenAI-compatible backend).

Usage:
  DEEPSEEK_API_KEY=... python3 -m deepdict.cli.generate_ab \
      --words work/ab-test/words.txt --out work/ab-test/deepseek-out.json
"""

import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from ..llm import ChatClient, with_retries
from ..schema import validate_entry


def build_user_prompt(word):
    return (
        "请为下面这个英文词生成词典义项。\n\n"
        f"输入词：{word}\n\n"
        "只输出符合要求的 JSON object。"
    )


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--words", type=Path, default=Path("work/ab-test/words.txt"))
    parser.add_argument("--prompt", type=Path, default=Path("deepdict/prompts/entry-generation-system.md"))
    parser.add_argument("--out", type=Path, default=Path("work/ab-test/deepseek-out.json"))
    parser.add_argument("--api-key-env", default="DEEPSEEK_API_KEY")
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--workers", type=int, default=10)
    parser.add_argument("--temperature", type=float, default=0.1)
    parser.add_argument("--max-tokens", type=int, default=1200)
    return parser.parse_args()


def main():
    args = parse_args()
    words = [w.strip() for w in args.words.read_text(encoding="utf-8").split() if w.strip()]
    system_prompt = args.prompt.read_text(encoding="utf-8").strip()

    kwargs = {"api_key_env": args.api_key_env, "temperature": args.temperature, "max_tokens": args.max_tokens}
    if args.base_url:
        kwargs["base_url"] = args.base_url
    if args.model:
        kwargs["model"] = args.model
    client = ChatClient.from_env(**kwargs)
    print(f"model={client.model} base_url={client.base_url} words={len(words)}")

    results = {}
    errors = {}

    def one(word):
        def call():
            data, usage = client.chat_json(system_prompt, build_user_prompt(word))
            return validate_entry(data, word), usage
        (entry, usage), _ = with_retries(call, retries=2)
        return word, entry, usage

    usage_total = {}
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(one, w): w for w in words}
        for fut in as_completed(futs):
            w = futs[fut]
            try:
                word, entry, usage = fut.result()
                results[word] = entry
                for k, v in (usage or {}).items():
                    if isinstance(v, (int, float)):
                        usage_total[k] = usage_total.get(k, 0) + v
                print(f"ok {word}")
            except Exception as exc:
                errors[w] = str(exc)
                print(f"FAIL {w}: {exc}")

    ordered = [results[w] for w in words if w in results]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(ordered, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"generated={len(ordered)}/{len(words)} errors={len(errors)}")
    print(f"usage={usage_total}")
    print(f"out={args.out}")


if __name__ == "__main__":
    raise SystemExit(main())
