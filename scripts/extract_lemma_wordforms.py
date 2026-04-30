#!/usr/bin/env python3
import argparse
import csv
from pathlib import Path


def is_single_word(value):
    return bool(value) and value.isalpha()


def parse_line(line):
    line = line.strip()
    if not line or line.startswith(";") or "->" not in line:
        return None

    left, right = line.split("->", 1)
    left = left.strip()
    right = right.strip()

    if "/" in left:
        word, frequency = left.rsplit("/", 1)
        word = word.strip()
        frequency = frequency.strip()
    else:
        word = left
        frequency = ""

    if not is_single_word(word):
        return None

    forms = []
    seen = set()
    word_key = word.casefold()

    for item in right.split(","):
        form = item.strip()
        form_key = form.casefold()
        if not is_single_word(form):
            continue
        if form_key == word_key or form_key in seen:
            continue
        seen.add(form_key)
        forms.append(form)

    return word, forms, frequency


def extract(input_path, output_path, include_frequency):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["word", "forms"]
    if include_frequency:
        fieldnames.append("frequency")

    with input_path.open("r", encoding="utf-8") as src:
        with output_path.open("w", encoding="utf-8", newline="") as dst:
            writer = csv.DictWriter(dst, fieldnames=fieldnames)
            writer.writeheader()

            for line in src:
                parsed = parse_line(line)
                if parsed is None:
                    continue

                word, forms, frequency = parsed
                row = {"word": word, "forms": "|".join(forms)}
                if include_frequency:
                    row["frequency"] = frequency
                writer.writerow(row)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input",
        default="vendor/ecdict/lemma.en.txt",
        help="Path to ECDICT lemma.en.txt.",
    )
    parser.add_argument(
        "--output",
        default="data/lemma-wordforms.csv",
        help="Output CSV path.",
    )
    parser.add_argument(
        "--include-frequency",
        action="store_true",
        help="Include the optional frequency column from lemma.en.txt.",
    )
    args = parser.parse_args()

    extract(Path(args.input), Path(args.output), args.include_frequency)


if __name__ == "__main__":
    main()
