#!/usr/bin/env python3
import argparse
import csv
from pathlib import Path


FORM_CODES = {"p", "d", "i", "3", "r", "t", "s"}


def parse_forms(word, exchange):
    forms = []
    seen = set()
    word_key = word.casefold()

    for item in (exchange or "").split("/"):
        if ":" not in item:
            continue
        code, value = item.split(":", 1)
        code = code.strip()
        value = value.strip()
        if code not in FORM_CODES or not value:
            continue

        value_key = value.casefold()
        if value_key == word_key or value_key in seen:
            continue

        seen.add(value_key)
        forms.append(value)

    return forms


def extract(input_path, output_path):
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with input_path.open("r", encoding="utf-8", newline="") as src:
        reader = csv.DictReader(src)
        with output_path.open("w", encoding="utf-8", newline="") as dst:
            writer = csv.DictWriter(dst, fieldnames=["word", "forms"])
            writer.writeheader()

            for row in reader:
                word = (row.get("word") or "").strip()
                if not word:
                    continue

                forms = parse_forms(word, row.get("exchange", ""))
                writer.writerow({"word": word, "forms": "|".join(forms)})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input",
        default="vendor/ecdict/ecdict.csv",
        help="Path to ECDICT CSV.",
    )
    parser.add_argument(
        "--output",
        default="data/ecdict-wordforms.csv",
        help="Output CSV path.",
    )
    args = parser.parse_args()

    extract(Path(args.input), Path(args.output))


if __name__ == "__main__":
    main()
