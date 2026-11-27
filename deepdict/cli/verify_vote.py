#!/usr/bin/env python3
"""Second independent verdict vote (codex/GPT-5.5) over already-flagged entries.

Takes the words DeepSeek flagged as problematic (work/qa/flagged-for-review.csv),
asks a different model (codex) the same adversarial verify question in batches,
and joins the two votes so we can keep only entries BOTH models call problematic
(high-confidence) and set aside the single-model ones (likely false positives) for
human review. Different model = independent errors, which is the whole point.
"""

import argparse
import csv
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from ..entries import iter_entries
from .generate_entries_batch import codex_generate
from .verify_entries import validate_verdict, VERDICTS

PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "verify-system.md"
PROBLEM = {"wrong_word", "fabricated", "wrong_senses", "partly_wrong"}


def build_batch_prompt(system_prompt, items):
    blocks = []
    for i, it in enumerate(items, 1):
        payload = {"word": it["word"], "senses": it["senses"]}
        line = (f"{i}. 输入词：{it['word']}\n   词条：{json.dumps(payload, ensure_ascii=False)}\n"
                f"   参考释义(ECDICT)：{it['ecdict'] or '（无）'}")
        if it["lookalike"]:
            line += f"\n   疑似混淆词：{it['lookalike']}"
        blocks.append(line)
    instr = (
        f"请逐一审查下面 {len(items)} 个词条，对每个按规则给出 verdict。\n"
        "输出一个 JSON 数组，每个元素是一个 verdict object（含 word/verdict/confidence/problems/note_zh），"
        "顺序与下面列表一致。只输出该 JSON 数组本身，无任何额外文字或代码块。\n\n"
        + "\n\n".join(blocks)
    )
    return system_prompt + "\n\n---\n\n" + instr


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--flagged", type=Path, default=Path("work/qa/flagged-for-review.csv"))
    ap.add_argument("--signals", type=Path, default=Path("work/qa/signals.csv"))
    ap.add_argument("--entries", type=Path, default=Path("work/entries"))
    ap.add_argument("--out", type=Path, default=Path("work/qa/vote.csv"))
    ap.add_argument("--batch-size", type=int, default=25)
    ap.add_argument("--workers", type=int, default=5)
    ap.add_argument("--reasoning", default="low")
    ap.add_argument("--timeout", type=float, default=600)
    args = ap.parse_args()

    flagged = list(csv.DictReader(args.flagged.open(encoding="utf-8")))
    ds = {r["word"]: r for r in flagged}
    sig = {r["word"]: r for r in csv.DictReader(args.signals.open(encoding="utf-8"))}
    wanted = set(ds)

    senses = {}
    for e in iter_entries(args.entries):
        if e.get("word") in wanted and e.get("include"):
            senses[e["word"]] = e.get("senses", [])

    items = []
    for w in ds:
        s = sig.get(w, {})
        items.append({"word": w, "senses": senses.get(w, []),
                      "ecdict": s.get("ecdict_translation", ""), "lookalike": s.get("lookalike", "")})

    system_prompt = PROMPT_PATH.read_text(encoding="utf-8").strip()
    batches = [items[i:i + args.batch_size] for i in range(0, len(items), args.batch_size)]
    print(f"flagged={len(items)} batches={len(batches)} workers={args.workers}")

    gpt = {}

    def run_one(batch):
        prompt = build_batch_prompt(system_prompt, batch)
        try:
            text = codex_generate(prompt, args.reasoning, None, args.timeout)
            raw = text.strip()
            if raw.startswith("```"):
                raw = raw.split("```", 2)[1]
                if raw.startswith("json"):
                    raw = raw[4:]
                raw = raw.strip()
            arr = json.loads(raw)
        except Exception as exc:
            return {"_error": str(exc)[:80], "n": len(batch)}
        out = {}
        for v in arr if isinstance(arr, list) else []:
            try:
                cv = validate_verdict(v, v.get("word"))
                out[cv["word"]] = cv
            except Exception:
                continue
        return out

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = [ex.submit(run_one, b) for b in batches]
        for i, fut in enumerate(as_completed(futs), 1):
            res = fut.result()
            if "_error" in res:
                print(f"[{i}/{len(batches)}] BATCH ERROR: {res['_error']}")
            else:
                gpt.update(res)
                print(f"[{i}/{len(batches)}] +{len(res)} verdicts (total {len(gpt)})")

    rows = []
    both = single = missing = 0
    for w, d in ds.items():
        g = gpt.get(w)
        gv = g["verdict"] if g else "(missing)"
        ds_problem = d["verdict"] in PROBLEM
        gpt_problem = gv in PROBLEM
        if g is None:
            agree = "missing"; missing += 1
        elif ds_problem and gpt_problem:
            agree = "both"; both += 1
        else:
            agree = "single"; single += 1
        rows.append({"word": w, "deepseek": d["verdict"], "gpt5": gv,
                     "agree": agree, "confidence_ds": d.get("confidence", ""),
                     "gpt_note": (g or {}).get("note_zh", ""),
                     "lookalike": sig.get(w, {}).get("lookalike", ""),
                     "gloss": sig.get(w, {}).get("gloss_zh_joined", "")[:40]})

    order = {"both": 0, "single": 1, "missing": 2}
    rows.sort(key=lambda r: (order[r["agree"]], r["deepseek"]))
    with args.out.open("w", encoding="utf-8", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=["word", "deepseek", "gpt5", "agree",
                                           "confidence_ds", "lookalike", "gloss", "gpt_note"])
        wr.writeheader()
        wr.writerows(rows)
    print(f"\nboth(高置信判删)={both}  single(仅DeepSeek,待复核)={single}  missing={missing}")
    print(f"out={args.out}")


if __name__ == "__main__":
    main()
