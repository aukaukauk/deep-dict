"""OpenAI-compatible chat client (DeepSeek by default) and a concurrent task runner.

The runner provides the shared machinery for LLM passes: worker pool, retry
with backoff, atomic per-item output, resume by file existence, run summaries.
"""

import json
import os
import random
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from .entries import write_json_atomic

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-v4-pro"


class ChatClient:
    def __init__(
        self,
        api_key,
        base_url=DEFAULT_BASE_URL,
        model=DEFAULT_MODEL,
        temperature=0.1,
        max_tokens=1200,
        timeout=60,
        thinking="disabled",
        reasoning_effort="auto",
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.thinking = thinking
        self.reasoning_effort = reasoning_effort

    @classmethod
    def from_env(cls, api_key_env="DEEPSEEK_API_KEY", **kwargs):
        api_key = os.environ.get(api_key_env)
        if not api_key:
            raise RuntimeError(f"Missing API key env var: {api_key_env}")
        base_url = os.environ.get("DEEPSEEK_BASE_URL", kwargs.pop("base_url", DEFAULT_BASE_URL))
        model = os.environ.get("DEEPSEEK_MODEL", kwargs.pop("model", DEFAULT_MODEL))
        return cls(api_key, base_url=base_url, model=model, **kwargs)

    def chat_json(self, system_prompt, user_prompt, temperature=None):
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {"type": "json_object"},
            "temperature": self.temperature if temperature is None else temperature,
            "max_tokens": self.max_tokens,
        }
        if self.thinking != "auto":
            payload["thinking"] = {"type": self.thinking}
        if self.reasoning_effort != "auto":
            payload["reasoning_effort"] = self.reasoning_effort

        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=body,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            data = json.loads(response.read().decode("utf-8"))

        try:
            choice = data["choices"][0]
            finish_reason = choice.get("finish_reason")
            content = choice["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError(f"unexpected API response shape: {data!r}") from exc

        if finish_reason == "length":
            raise ValueError("model output was truncated")
        if not content:
            raise ValueError("empty model output")
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ValueError(f"model did not return valid JSON: {content[:500]!r}") from exc
        return parsed, data.get("usage", {})


def add_usage(total, usage):
    if not isinstance(usage, dict):
        return
    for key, value in usage.items():
        if isinstance(value, (int, float)):
            total[key] = total.get(key, 0) + value
        elif isinstance(value, dict):
            nested = total.setdefault(key, {})
            add_usage(nested, value)


def with_retries(fn, retries=2, base_sleep=1.0, max_sleep=20.0, jitter=0.5):
    """Run fn() with exponential backoff. Returns (result, attempts).

    fn must raise on failure; the last exception propagates after retries
    are exhausted.
    """
    last_error = None
    for attempt in range(1, retries + 2):
        try:
            return fn(), attempt
        except Exception as exc:
            last_error = exc
            if attempt <= retries:
                sleep_seconds = min(max_sleep, base_sleep * (2 ** (attempt - 1)))
                sleep_seconds += random.uniform(0, jitter)
                time.sleep(sleep_seconds)
    raise last_error


def run_tasks(items, process_one, workers=8, run_summary_path=None, run_meta=None):
    """Run process_one(item) -> (status, label, usage) over a worker pool.

    status is a free-form short string ("ok", "skipped", "failed", ...);
    counts are aggregated per status. A summary JSON is written to
    run_summary_path when given. Returns the counts dict.
    """
    counts = {}
    usage_total = {}
    started_at = datetime.now(timezone.utc)
    total = len(items)

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(process_one, item): item for item in items}
        done = 0
        for future in as_completed(futures):
            try:
                status, label, usage = future.result()
            except Exception as exc:  # process_one should catch; this is a backstop
                status, label, usage = "crashed", repr(futures[future]), {}
                print(f"crashed: {exc}", file=sys.stderr)
            counts[status] = counts.get(status, 0) + 1
            add_usage(usage_total, usage)
            done += 1
            print(f"[{done}/{total}] {status} {label}", flush=True)

    finished_at = datetime.now(timezone.utc)
    summary = {
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "duration_seconds": round((finished_at - started_at).total_seconds(), 3),
        "counts": counts,
        "usage": usage_total,
    }
    if run_meta:
        summary.update(run_meta)
    if run_summary_path is not None:
        write_json_atomic(run_summary_path, summary)
        print(f"run_summary={run_summary_path}")
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return counts
