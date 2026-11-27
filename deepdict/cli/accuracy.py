#!/usr/bin/env python3
"""Accuracy check: stratified sample, collect verdicts, report estimates.

  sample   draw a stratified sample of included entries (needs the QA scan
           output, work/qa/signals.csv)
  collect  merge the judges' verdict files into dictionary/accuracy.csv
  report   print weighted estimates from dictionary/accuracy.csv

Strata are risk tier (from the QA scan) x frequency band. Each stratum gets a
floor, and the rest of the sample is allocated in proportion to stratum size.
Estimates weight every stratum by its share of the dictionary, so they
describe the whole dictionary rather than the sample. Confidence intervals
come from a bootstrap within strata.

Between `sample` and `collect`, each sampled entry is compared with reference
dictionaries by a judge following deepdict/prompts/accuracy-judge.md. The
reference text itself is not kept in this repository.

Usage:
  python3 -m deepdict.cli.accuracy sample --size 800
  python3 -m deepdict.cli.accuracy collect
  python3 -m deepdict.cli.accuracy report
"""

import argparse
import csv
import json
import random
from collections import Counter, defaultdict
from pathlib import Path

VERDICTS = ["correct", "minor", "wrong", "unverifiable"]
BANDS = ["hi", "mid", "low", "tail"]
FIELDS = [
    "word", "freq_band", "risk_tier", "stratum_population", "stratum_sampled",
    "in_reference", "verdict", "judge_verdict", "note",
]


def band(zipf):
    if zipf >= 4:
        return "hi"
    if zipf >= 3:
        return "mid"
    if zipf >= 2:
        return "low"
    return "tail"


def cmd_sample(args):
    strata = defaultdict(list)
    with args.signals.open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            strata[(row.get("tier") or "clean", band(float(row["zipf"])))].append(row)

    alloc = {key: min(len(rows), args.floor) for key, rows in strata.items()}
    rest = args.size - sum(alloc.values())
    room = {key: len(rows) - alloc[key] for key, rows in strata.items()}
    room_total = sum(room.values())
    extra = {key: rest * room[key] / room_total for key in strata}
    for key in strata:
        alloc[key] += int(extra[key])
    leftover = args.size - sum(alloc.values())
    for key in sorted(strata, key=lambda k: extra[k] - int(extra[k]), reverse=True)[:leftover]:
        alloc[key] += 1

    rng = random.Random(args.seed)
    rows = []
    for key in sorted(strata):
        for row in rng.sample(strata[key], alloc[key]):
            rows.append({"word": row["word"], "tier": key[0], "band": key[1], "zipf": row["zipf"]})
    rng.shuffle(rows)

    args.work_dir.mkdir(parents=True, exist_ok=True)
    with (args.work_dir / "sample.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["word", "tier", "band", "zipf"])
        writer.writeheader()
        writer.writerows(rows)
    summary = {f"{k[0]}/{k[1]}": {"population": len(v), "sampled": alloc[k]} for k, v in sorted(strata.items())}
    (args.work_dir / "strata.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(f"population={sum(len(v) for v in strata.values())} sampled={len(rows)} dir={args.work_dir}")


def cmd_collect(args):
    with (args.work_dir / "sample.csv").open("r", encoding="utf-8", newline="") as f:
        sample = {row["word"]: row for row in csv.DictReader(f)}
    strata = json.loads((args.work_dir / "strata.json").read_text(encoding="utf-8"))
    verdicts = {}
    for path in sorted((args.work_dir / "verdicts").glob("*.json")):
        for verdict in json.loads(path.read_text(encoding="utf-8")):
            verdicts[verdict["word"]] = verdict
    overrides_path = args.work_dir / "overrides.json"
    overrides = json.loads(overrides_path.read_text(encoding="utf-8")) if overrides_path.exists() else {}

    missing = [word for word in sample if word not in verdicts]
    invalid = [word for word, v in verdicts.items() if v.get("verdict") not in VERDICTS]
    unknown = [word for word in list(verdicts) + list(overrides) if word not in sample]
    if missing or invalid or unknown:
        raise SystemExit(f"missing={missing[:5]} invalid={invalid[:5]} unknown={unknown[:5]}")

    rows = []
    for word, s in sample.items():
        judged = verdicts[word]
        final = overrides.get(word, {})
        stratum = strata[f"{s['tier']}/{s['band']}"]
        note = judged.get("problem", "")
        if final.get("reason"):
            note = f"[{final['reason']}] {note}".strip()
        rows.append({
            "word": word,
            "freq_band": s["band"],
            "risk_tier": s["tier"],
            "stratum_population": stratum["population"],
            "stratum_sampled": stratum["sampled"],
            "in_reference": "yes" if judged.get("ref_coverage") == "found" else "no",
            "verdict": final.get("verdict", judged["verdict"]),
            "judge_verdict": judged["verdict"],
            "note": note,
        })
    rows.sort(key=lambda r: (VERDICTS.index(r["verdict"]), r["word"]))
    with args.results.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"rows={len(rows)} overrides={len(overrides)} results={args.results}")


def load_results(path):
    groups = defaultdict(list)
    population = {}
    with path.open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            key = (row["risk_tier"], row["freq_band"])
            groups[key].append(row)
            population[key] = int(row["stratum_population"])
    return groups, population


def estimate(groups, population, pred, cond):
    num = den = 0.0
    for key, rows in groups.items():
        if not rows:
            continue
        num += population[key] * sum(1 for r in rows if cond(r) and pred(r)) / len(rows)
        den += population[key] * sum(1 for r in rows if cond(r)) / len(rows)
    return num / den if den else float("nan")


def interval(groups, population, pred, cond, reps, seed=1):
    rng = random.Random(seed)
    values = []
    for _ in range(reps):
        resampled = {key: [rng.choice(rows) for _ in rows] for key, rows in groups.items()}
        values.append(estimate(resampled, population, pred, cond))
    values = sorted(v for v in values if v == v)
    return values[int(0.025 * len(values))], values[int(0.975 * len(values)) - 1]


def cmd_report(args):
    groups, population = load_results(args.results)
    rows = [r for rs in groups.values() for r in rs]
    everything = lambda r: True

    def line(label, pred, cond=everything, subset=None):
        g = subset if subset is not None else groups
        p = estimate(g, population, pred, cond)
        lo, hi = interval(g, population, pred, cond, args.reps)
        print(f"  {label:26s} {100 * p:5.1f}%   95% CI {100 * lo:4.1f}-{100 * hi:4.1f}%")

    def block(title, cond=everything, subset=None, verdicts=VERDICTS):
        g = subset if subset is not None else groups
        n = sum(1 for rs in g.values() for r in rs if cond(r))
        share = estimate(g, population, cond, everything) if subset is None else None
        suffix = f", {100 * share:.0f}% of dictionary" if share is not None and cond is not everything else ""
        print(f"\n{title} (n={n}{suffix})")
        for verdict in verdicts:
            line(verdict, lambda r, v=verdict: r["verdict"] == v, cond, subset)

    print(f"sample={len(rows)} dictionary={sum(population.values())}")
    print("raw counts:", dict(Counter(r["verdict"] for r in rows)))
    block("whole dictionary")
    block("in a reference dictionary", lambda r: r["in_reference"] == "yes")
    block("not in any reference dictionary", lambda r: r["in_reference"] == "no")
    for name in BANDS:
        subset = {key: rs for key, rs in groups.items() if key[1] == name}
        share = sum(population[key] for key in subset) / sum(population.values())
        block(f"frequency band {name} ({100 * share:.0f}% of dictionary)", subset=subset, verdicts=VERDICTS[:3])


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("action", choices=["sample", "collect", "report"])
    parser.add_argument("--signals", type=Path, default=Path("work/qa/signals.csv"))
    parser.add_argument("--work-dir", type=Path, default=Path("work/accuracy"))
    parser.add_argument("--results", type=Path, default=Path("dictionary/accuracy.csv"))
    parser.add_argument("--size", type=int, default=800)
    parser.add_argument("--floor", type=int, default=20, help="Minimum sample per stratum.")
    parser.add_argument("--seed", type=int, default=20261126)
    parser.add_argument("--reps", type=int, default=2000, help="Bootstrap repetitions.")
    return parser.parse_args()


def main():
    args = parse_args()
    {"sample": cmd_sample, "collect": cmd_collect, "report": cmd_report}[args.action](args)


if __name__ == "__main__":
    main()
