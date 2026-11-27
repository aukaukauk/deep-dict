#!/usr/bin/env python3
"""Build the MDict and StarDict packages from the entries.

Writes dictionary/DeepDict.mdx and dictionary/DeepDict.stardict.zip, then
reads both back and checks every article against the source entries.

Usage:
  python3 -m deepdict.cli.build_formats
"""

import argparse
import shutil
from pathlib import Path

from .. import __version__
from ..build.html import entry_html
from ..build.mdict import read_mdx, write_mdx
from ..build.render import load_entries
from ..build.stardict import read_stardict, write_stardict, zip_files


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--entries-dir", type=Path, default=Path("work/entries"))
    parser.add_argument("--out-dir", type=Path, default=Path("dictionary"))
    parser.add_argument("--work-dir", type=Path, default=Path("work/build-formats"))
    parser.add_argument("--name", default="DeepDict")
    parser.add_argument("--formats", default="mdict,stardict")
    return parser.parse_args()


def check(label, expected, actual):
    actual = dict(actual)
    if len(actual) != len(expected):
        raise SystemExit(f"{label}: read back {len(actual)} articles, expected {len(expected)}")
    wrong = [word for word, html in expected.items() if actual.get(word) != html]
    if wrong:
        raise SystemExit(f"{label}: {len(wrong)} articles differ, e.g. {wrong[:5]}")
    print(f"{label}: {len(actual)} articles verified")


def main():
    args = parse_args()
    formats = {name.strip() for name in args.formats.split(",") if name.strip()}
    entries = load_entries(args.entries_dir)
    words = [entry["word"] for entry in entries]
    if len(set(words)) != len(words):
        raise SystemExit("duplicate headwords in entries")
    description = f"DeepDict {__version__}：英汉离线词典，{len(entries)} 词，词条由 LLM 生成。"

    if args.work_dir.exists():
        shutil.rmtree(args.work_dir)
    args.work_dir.mkdir(parents=True)
    args.out_dir.mkdir(parents=True, exist_ok=True)

    if "mdict" in formats:
        expected = {entry["word"]: entry_html(entry, with_headword=True) for entry in entries}
        mdx_path = args.out_dir / f"{args.name}.mdx"
        write_mdx(mdx_path, args.work_dir / f"{args.name}.mdx.txt", expected.items(), args.name, description)
        check("mdict", expected, read_mdx(mdx_path))
        print(f"mdict={mdx_path}")

    if "stardict" in formats:
        expected = {entry["word"]: entry_html(entry, with_headword=False) for entry in entries}
        folder = args.work_dir / f"{args.name}-stardict"
        paths = write_stardict(folder, args.name, expected.items(), args.name, description, "DeepDict Project")
        check("stardict", expected, read_stardict(folder, args.name))
        zip_path = args.out_dir / f"{args.name}.stardict.zip"
        zip_files(zip_path, paths, f"{args.name}-stardict")
        print(f"stardict={zip_path}")


if __name__ == "__main__":
    main()
