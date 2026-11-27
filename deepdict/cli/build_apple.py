#!/usr/bin/env python3
"""Build Apple Dictionary DDK source from an entries directory.

Usage:
  python3 -m deepdict.cli.build_apple --entries-dir work/entries \
      --output-dir build/deep-dict-v2 --clean
"""

import argparse
import csv
import shutil
from html import escape
from pathlib import Path

from ..build.render import load_entries, write_css, write_xml


def load_wordforms(path):
    forms_by_word = {}
    with Path(path).open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            word = (row.get("word") or "").strip()
            if not word:
                continue
            forms = []
            seen = {word.casefold()}
            for value in (row.get("forms") or "").split("|"):
                form = value.strip()
                key = form.casefold()
                if not form or key in seen:
                    continue
                seen.add(key)
                forms.append(form)
            forms_by_word[word] = forms
    return forms_by_word


def plist_text(args):
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleDevelopmentRegion</key>
  <string>zh_CN</string>
  <key>CFBundleDisplayName</key>
  <string>{escape(args.display_name)}</string>
  <key>CFBundleIdentifier</key>
  <string>{escape(args.bundle_id)}</string>
  <key>CFBundleInfoDictionaryVersion</key>
  <string>6.0</string>
  <key>CFBundleName</key>
  <string>{escape(args.dict_name)}</string>
  <key>CFBundleShortVersionString</key>
  <string>{escape(args.version)}</string>
  <key>DCSDictionaryCopyright</key>
  <string>{escape(args.copyright)}</string>
  <key>DCSDictionaryCSS</key>
  <string>DefaultStyle.css</string>
  <key>DCSDictionaryFrontMatterReferenceID</key>
  <string>frontmatter</string>
  <key>DCSDictionaryLanguages</key>
  <array>
    <dict>
      <key>DCSDictionaryDescriptionLanguage</key>
      <string>zh_CN</string>
      <key>DCSDictionaryIndexLanguage</key>
      <string>en</string>
    </dict>
  </array>
  <key>DCSDictionaryManufacturerName</key>
  <string>{escape(args.manufacturer)}</string>
  <key>DCSDictionaryNativeDisplayName</key>
  <string>{escape(args.display_name)}</string>
  <key>DCSDictionaryPrimaryLanguage</key>
  <string>zh_CN</string>
  <key>DCSDictionaryUseSystemAppearance</key>
  <true/>
</dict>
</plist>
'''


def makefile_text(args):
    return f"""DICT_BUILD_TOOL_DIR ?= /Applications/Xcode.app/Contents/Developer/Extras/Dictionary Development Kit
DICT_BUILD_TOOL_BIN = $(DICT_BUILD_TOOL_DIR)/bin
DICT_DEV_KIT_OBJ_DIR = ./objects
export DICT_DEV_KIT_OBJ_DIR

DICT_NAME = {args.package_name}
DICT_SRC_PATH = {args.xml_name}
CSS_PATH = DefaultStyle.css
PLIST_PATH = Info.plist
DICT_BUILD_OPTS =

DESTINATION_FOLDER = $(HOME)/Library/Dictionaries

all:
\t"$(DICT_BUILD_TOOL_BIN)/build_dict.sh" $(DICT_BUILD_OPTS) "$(DICT_NAME)" "$(DICT_SRC_PATH)" "$(CSS_PATH)" "$(PLIST_PATH)"
\techo "Done."

install:
\techo "Installing into $(DESTINATION_FOLDER)."
\tmkdir -p $(DESTINATION_FOLDER)
\tditto --noextattr --norsrc "$(DICT_DEV_KIT_OBJ_DIR)/$(DICT_NAME).dictionary" "$(DESTINATION_FOLDER)/$(DICT_NAME).dictionary"
\ttouch $(DESTINATION_FOLDER)
\techo "Done."
\techo "To test the new dictionary, try Dictionary.app."

clean:
\t/bin/rm -rf $(DICT_DEV_KIT_OBJ_DIR)
"""


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--entries-dir", type=Path, default=Path("work/entries"))
    parser.add_argument("--wordforms", type=Path, default=Path("data/lemma-wordforms.csv"))
    parser.add_argument("--index-mode", choices=["headword", "wordforms"], default="headword")
    parser.add_argument("--output-dir", type=Path, default=Path("build/deep-dict-v2"))
    parser.add_argument("--dict-name", default="DeepDict")
    parser.add_argument("--package-name", default="DeepDict")
    parser.add_argument("--display-name", default="DeepDict")
    parser.add_argument("--bundle-id", default="org.deepdict.dictionary.en-zh")
    parser.add_argument("--version", default="0.2.0")
    parser.add_argument("--manufacturer", default="DeepDict Project")
    parser.add_argument("--copyright", default="Generated dictionary data. Review before redistribution.")
    parser.add_argument("--xml-name", default="DeepDict.xml")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--clean", action="store_true")
    return parser.parse_args()


def main():
    args = parse_args()
    if args.clean and args.output_dir.exists():
        shutil.rmtree(args.output_dir)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    entries = load_entries(args.entries_dir, args.limit)
    forms_by_word = load_wordforms(args.wordforms) if args.index_mode == "wordforms" else {}

    xml_path = args.output_dir / args.xml_name
    write_xml(xml_path, entries, forms_by_word, args.dict_name)
    write_css(args.output_dir / "DefaultStyle.css")
    (args.output_dir / "Info.plist").write_text(plist_text(args), encoding="utf-8")
    (args.output_dir / "Makefile").write_text(makefile_text(args), encoding="utf-8")

    print(f"entries={len(entries)}")
    print(f"xml={xml_path}")
    print(f"output_dir={args.output_dir}")


if __name__ == "__main__":
    main()
