#!/usr/bin/env python3
"""Draw a stratified gold-standard sample for human labeling.

Samples words from the qa_scan signals table, stratified by risk tier and
zipf band, so the labeled set covers common words, tail words, and every
risk slice. The output CSV has empty label/note columns; after one human
pass, this file becomes the measuring stick for every QA strategy, prompt
revision, and model change (查全率/误报率 are computed against it).

Labels suggested: ok / wrong_word / fabricated / wrong_senses / partly_wrong.

Usage:
  python3 -m deepdict.cli.gold_sample --size 500
"""

import argparse
import csv
import random
from collections import defaultdict
from pathlib import Path


def zipf_band(zipf):
    if zipf >= 4:
        return "hi"
    if zipf >= 3:
        return "mid"
    if zipf >= 2:
        return "low"
    return "tail"


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--signals", type=Path, default=Path("work/qa/signals.csv"))
    parser.add_argument("--out", type=Path, default=Path("work/qa/gold-sample.csv"))
    parser.add_argument("--size", type=int, default=500)
    parser.add_argument("--seed", type=int, default=20260612)
    return parser.parse_args()


def main():
    args = parse_args()
    strata = defaultdict(list)
    with args.signals.open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            tier = row.get("tier") or "clean"
            band = zipf_band(float(row["zipf"]))
            strata[(tier, band)].append(row)

    rng = random.Random(args.seed)
    per_stratum = max(1, args.size // len(strata))
    sample = []
    for key in sorted(strata):
        rows = strata[key]
        take = rows if len(rows) <= per_stratum else rng.sample(rows, per_stratum)
        sample.extend(take)
    rng.shuffle(sample)
    sample = sample[: args.size]

    fieldnames = [
        "word", "zipf", "tier", "lookalike", "gloss_zh_joined",
        "ecdict_translation", "label", "note",
    ]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in sample:
            writer.writerow({
                "word": row["word"],
                "zipf": row["zipf"],
                "tier": row.get("tier") or "clean",
                "lookalike": row.get("lookalike", ""),
                "gloss_zh_joined": row.get("gloss_zh_joined", ""),
                "ecdict_translation": row.get("ecdict_translation", ""),
                "label": "",
                "note": "",
            })
    print(f"strata={len(strata)} sampled={len(sample)} out={args.out}")


if __name__ == "__main__":
    main()
