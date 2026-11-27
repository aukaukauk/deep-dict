#!/usr/bin/env python3
"""Token-free hallucination triage over generated entries.

Combines, per included entry:
  - wordfreq zipf frequency
  - lookalike risk (rare word with a much more frequent edit-distance<=2
    neighbor; the deference/difference trap)
  - ECDICT existence + Chinese gloss corroboration
  - the model's own suitability/confidence scores

and writes ranked risk CSVs plus a summary report under --out. Costs zero
API tokens; the top tiers are the input slice for the LLM verify pass.

Usage:
  python3 -m deepdict.cli.qa_scan --entries work/entries --out work/qa
"""

import argparse
import csv
import json
from collections import Counter
from pathlib import Path

from wordfreq import top_n_list, zipf_frequency

from ..entries import iter_entries
from ..qa.ecdict import gloss_overlap, load_translations
from ..qa.lookalike import build_deletion_index, find_lookalikes


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--entries", type=Path, default=Path("work/entries"))
    parser.add_argument("--ecdict", type=Path, default=Path("work/vendor/ecdict/ecdict.csv"))
    parser.add_argument("--out", type=Path, default=Path("work/qa"))
    parser.add_argument("--vocab-size", type=int, default=30000,
                        help="High-frequency vocabulary size for lookalike candidates.")
    parser.add_argument("--rare-zipf", type=float, default=3.5,
                        help="Only words rarer than this are lookalike-checked.")
    parser.add_argument("--min-len", type=int, default=5,
                        help="Minimum word length for lookalike checking.")
    parser.add_argument("--zipf-gap", type=float, default=1.5,
                        help="Neighbor must be at least this much more frequent (zipf).")
    parser.add_argument("--no-evidence-zipf", type=float, default=2.5,
                        help="Below this zipf, absence from ECDICT becomes a signal.")
    return parser.parse_args()


def fmt(value):
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.3f}"
    return value


def write_csv(path, rows, fieldnames):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: fmt(row.get(k)) for k in fieldnames})


def main():
    args = parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    print(f"loading ECDICT from {args.ecdict} ...", flush=True)
    translations = load_translations(args.ecdict)
    print(f"ecdict_words={len(translations)}", flush=True)

    print(f"building lookalike index over top {args.vocab_size} words ...", flush=True)
    vocab = [w for w in top_n_list("en", args.vocab_size) if w.isalpha() and len(w) >= 3]
    vocab_zipf = {w: zipf_frequency(w, "en") for w in vocab}
    index = build_deletion_index(vocab, depth=2)
    print(f"vocab={len(vocab)} index_keys={len(index)}", flush=True)

    rows = []
    excluded = 0
    scanned = 0
    for entry in iter_entries(args.entries):
        if not entry.get("include"):
            excluded += 1
            continue
        scanned += 1
        if scanned % 10000 == 0:
            print(f"scanned {scanned} included entries ...", flush=True)

        word = entry["word"]
        lower = word.lower()
        zipf = zipf_frequency(lower, "en")
        translation = translations.get(lower)
        in_ecdict = translation is not None
        overlap = gloss_overlap(entry, translation) if in_ecdict else None

        neighbor = None
        neighbor_zipf = None
        neighbor_dist = None
        neighbor_overlap = None
        if zipf < args.rare_zipf and len(lower) >= args.min_len and lower.isalpha():
            # Distance-2 hits are weak evidence on short words: nearly every
            # rare 5-letter word has some common word two edits away. Require
            # more length and a bigger frequency gap as distance grows.
            for dist, candidate in find_lookalikes(lower, index):
                gap = vocab_zipf[candidate] - zipf
                if dist == 1 and gap >= args.zipf_gap:
                    pass
                elif dist == 2 and len(lower) >= 7 and gap >= args.zipf_gap + 1.0:
                    pass
                else:
                    continue
                neighbor, neighbor_zipf, neighbor_dist = candidate, vocab_zipf[candidate], dist
                neighbor_translation = translations.get(candidate)
                if neighbor_translation:
                    neighbor_overlap = gloss_overlap(entry, neighbor_translation)
                break

        # ECDICT arbitration: if the generated gloss matches the neighbor's
        # ECDICT translation better than the word's own, the model wrote the
        # neighbor's meaning -- direct misread evidence. A good match with the
        # word's own translation clears the lookalike suspicion instead.
        own = overlap if overlap is not None else -1.0
        signal_misread = (
            neighbor_overlap is not None
            and neighbor_overlap >= 0.5
            and neighbor_overlap - own >= 0.25
        )
        corroborated = overlap is not None and overlap >= 0.34
        signal_lookalike = neighbor is not None and not signal_misread and not corroborated
        signal_zero_overlap = in_ecdict and overlap == 0.0
        signal_no_evidence = (not in_ecdict) and zipf < args.no_evidence_zipf
        signal_low_self = (
            entry.get("meaning_confidence", 10) <= 7
            or entry.get("suitability_score", 10) <= 6
        )

        strong = sum([signal_misread, signal_zero_overlap, signal_no_evidence])
        if signal_misread or strong >= 2:
            tier = "A"
        elif strong == 1:
            tier = "B"
        elif signal_lookalike or signal_low_self:
            tier = "C"
        else:
            tier = ""

        rows.append({
            "word": word,
            "zipf": zipf,
            "in_ecdict": int(in_ecdict),
            "gloss_overlap": overlap,
            "lookalike": neighbor,
            "lookalike_zipf": neighbor_zipf,
            "lookalike_dist": neighbor_dist,
            "lookalike_overlap": neighbor_overlap,
            "meaning_confidence": entry.get("meaning_confidence"),
            "suitability_score": entry.get("suitability_score"),
            "signal_misread": int(signal_misread),
            "signal_lookalike": int(signal_lookalike),
            "signal_zero_overlap": int(signal_zero_overlap),
            "signal_no_evidence": int(signal_no_evidence),
            "signal_low_self": int(signal_low_self),
            "strong_signals": strong,
            "tier": tier,
            "gloss_zh_joined": "；".join(
                s.get("gloss_zh", "") for s in entry.get("senses", [])
            ),
            "ecdict_translation": (translation or "").replace("\n", " / ")[:120],
        })

    fieldnames = list(rows[0].keys()) if rows else []
    write_csv(args.out / "signals.csv", rows, fieldnames)

    def subset(predicate, sort_key):
        return sorted((r for r in rows if predicate(r)), key=sort_key)

    misread_rows = subset(
        lambda r: r["signal_misread"],
        lambda r: -(r["lookalike_overlap"] or 0),
    )
    lookalike_rows = subset(
        lambda r: r["signal_lookalike"],
        lambda r: (r["lookalike_dist"], -(r["lookalike_zipf"] - r["zipf"])),
    )
    zero_overlap_rows = subset(lambda r: r["signal_zero_overlap"], lambda r: r["zipf"])
    no_evidence_rows = subset(lambda r: r["signal_no_evidence"], lambda r: r["zipf"])
    ranked = subset(
        lambda r: r["tier"] in ("A", "B"),
        lambda r: (r["tier"], -r["strong_signals"], r["zipf"]),
    )

    write_csv(args.out / "misread.csv", misread_rows, fieldnames)
    write_csv(args.out / "lookalike.csv", lookalike_rows, fieldnames)
    write_csv(args.out / "zero-overlap.csv", zero_overlap_rows, fieldnames)
    write_csv(args.out / "no-evidence.csv", no_evidence_rows, fieldnames)
    write_csv(args.out / "risk-ranked.csv", ranked, fieldnames)

    tiers = Counter(r["tier"] for r in rows)
    summary = {
        "included_entries": scanned,
        "excluded_entries": excluded,
        "tier_A": tiers.get("A", 0),
        "tier_B": tiers.get("B", 0),
        "tier_C": tiers.get("C", 0),
        "untiered": tiers.get("", 0),
        "signal_misread": len(misread_rows),
        "signal_lookalike": len(lookalike_rows),
        "signal_zero_overlap": len(zero_overlap_rows),
        "signal_no_evidence": len(no_evidence_rows),
        "in_ecdict": sum(r["in_ecdict"] for r in rows),
    }
    (args.out / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    lines = [
        "# QA triage report",
        "",
        f"- included entries scanned: {scanned} (excluded: {excluded})",
        f"- in ECDICT: {summary['in_ecdict']} "
        f"({summary['in_ecdict'] / max(scanned, 1):.1%})",
        "",
        "## Risk tiers",
        "",
        f"- tier A (>=2 strong signals, verify first): {summary['tier_A']}",
        f"- tier B (1 strong signal): {summary['tier_B']}",
        f"- tier C (low self-reported scores only): {summary['tier_C']}",
        f"- no signal: {summary['untiered']}",
        "",
        "## Signals",
        "",
        f"- misread evidence (gloss matches the neighbor's ECDICT translation, not the word's): {summary['signal_misread']}",
        f"- unresolved lookalike (frequent neighbor, gloss not corroborated): {summary['signal_lookalike']}",
        f"- zero gloss overlap vs ECDICT (possible fabricated senses): {summary['signal_zero_overlap']}",
        f"- rare + absent from ECDICT (no independent evidence): {summary['signal_no_evidence']}",
        "",
        "Top misread examples (strongest evidence first):",
        "",
    ]
    for row in misread_rows[:20]:
        lines.append(
            f"- `{row['word']}` (zipf {row['zipf']:.2f}) reads as `{row['lookalike']}` "
            f"(overlap with neighbor {row['lookalike_overlap']:.2f} vs own "
            f"{row['gloss_overlap'] if row['gloss_overlap'] is not None else 'n/a'}) "
            f"gloss: {row['gloss_zh_joined'][:40]}"
        )
    (args.out / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"out={args.out}")


if __name__ == "__main__":
    main()
