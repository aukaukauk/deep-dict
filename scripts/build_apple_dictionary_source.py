#!/usr/bin/env python3
import argparse
import csv
import json
import re
import shutil
from html import escape
from pathlib import Path


DEFAULT_DICT_NAME = "Concept English-Chinese Dictionary"
DEFAULT_PACKAGE_NAME = "ConceptEnglishChineseDictionary"
DEFAULT_BUNDLE_ID = "org.openconcept.dictionary.en-zh"
DEFAULT_VERSION = "0.1.0"


POS_LABELS = {
    "n.": "名词",
    "v.": "动词",
    "adj.": "形容词",
    "adv.": "副词",
    "prep.": "介词",
    "pron.": "代词",
    "conj.": "连词",
    "interj.": "感叹词",
    "det.": "限定词",
    "num.": "数词",
    "aux.": "助动词",
    "modal": "情态动词",
    "prefix": "前缀",
    "suffix": "后缀",
}


def stable_id(word):
    slug = re.sub(r"[^A-Za-z0-9]+", "_", word).strip("_").lower()
    return f"w_{slug}" if slug else "w_entry"


def load_wordforms(path):
    forms_by_word = {}
    with path.open("r", encoding="utf-8", newline="") as f:
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


def load_entries(input_dir, limit):
    entries = []
    for path in sorted(input_dir.glob("*.json")):
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if data.get("include") is False:
            continue
        if not data.get("senses"):
            continue
        entries.append(data)
        if limit and len(entries) >= limit:
            break
    entries.sort(key=lambda item: item["word"].casefold())
    return entries


def sense_html(sense):
    pos = sense.get("pos", "").strip()
    context = sense.get("context_label", "").strip()
    gloss = sense.get("gloss_zh", "").strip()
    definition = sense.get("definition_zh", "").strip()

    bits = ['<li class="sense">']
    if pos:
        title = POS_LABELS.get(pos, pos)
        bits.append(f'<span class="pos" title="{escape(title)}">{escape(pos)}</span>')
    if context:
        bits.append(f'<span class="label">{escape(context)}</span>')
    bits.append(f'<span class="gloss">{escape(gloss)}</span>')
    if definition:
        bits.append(f'<div class="definition">{escape(definition)}</div>')
    bits.append("</li>")
    return "".join(bits)


def entry_xml(entry, forms):
    word = entry["word"]
    entry_id = stable_id(word)
    title = escape(word, quote=True)
    indexes = [word] + forms
    seen = set()

    lines = [f'  <d:entry id="{entry_id}" d:title="{title}">']
    for value in indexes:
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        escaped_value = escape(value, quote=True)
        lines.append(f'    <d:index d:value="{escaped_value}" d:title="{title}"/>')
    lines.append(f'    <h1>{escape(word)}</h1>')
    lines.append("    <ol class=\"senses\">")
    for sense in entry["senses"]:
        lines.append(f"      {sense_html(sense)}")
    lines.append("    </ol>")
    lines.append("  </d:entry>")
    return "\n".join(lines)


def front_matter_xml(dict_name, entry_count):
    return f'''  <d:entry id="frontmatter" d:title="{escape(dict_name, quote=True)}">
    <d:index d:value="{escape(dict_name, quote=True)}"/>
    <h1>{escape(dict_name)}</h1>
    <p>Generated English-Chinese concept dictionary.</p>
    <p>Entries: {entry_count}</p>
  </d:entry>'''


def write_xml(path, entries, forms_by_word, dict_name):
    with path.open("w", encoding="utf-8", newline="\n") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        f.write(
            '<d:dictionary xmlns="http://www.w3.org/1999/xhtml" '
            'xmlns:d="http://www.apple.com/DTDs/DictionaryService-1.0.rng">\n'
        )
        f.write(front_matter_xml(dict_name, len(entries)))
        f.write("\n")
        for entry in entries:
            f.write(entry_xml(entry, forms_by_word.get(entry["word"], [])))
            f.write("\n")
        f.write("</d:dictionary>\n")


def write_css(path):
    path.write_text(
        """body {
  font-family: -apple-system, BlinkMacSystemFont, "Helvetica Neue", Arial, sans-serif;
  line-height: 1.45;
  color: -apple-system-label;
}

h1 {
  font-size: 1.45em;
  margin: 0 0 0.55em;
  font-weight: 650;
}

.senses {
  margin: 0;
  padding-left: 1.35em;
}

.sense {
  margin: 0.36em 0;
}

.pos {
  color: #666;
  font-size: 0.88em;
  margin-right: 0.45em;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}

.label {
  color: #345995;
  background: rgba(52, 89, 149, 0.10);
  border-radius: 3px;
  padding: 0.05em 0.28em;
  margin-right: 0.45em;
  font-size: 0.86em;
}

.gloss {
  font-weight: 520;
}

.definition {
  color: #555;
  margin-top: 0.16em;
}
""",
        encoding="utf-8",
    )


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


def write_makefile(path, args):
    # This follows the variable names used by Apple's Dictionary Development Kit.
    path.write_text(
        f"""DICT_BUILD_TOOL_DIR ?= /Applications/Xcode.app/Contents/Developer/Extras/Dictionary Development Kit
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
""",
        encoding="utf-8",
    )


def write_readme(path, args):
    path.write_text(
        f"""# {args.dict_name}

This directory contains Apple Dictionary Development Kit source files generated from `outputs/entries`.

## Files

- `{args.xml_name}`: dictionary entries in Apple DDK XHTML/XML format
- `DefaultStyle.css`: entry styling
- `Info.plist`: dictionary bundle metadata
- `Makefile`: Apple DDK build entrypoint

## Build

This machine currently needs Apple's Dictionary Development Kit to compile the source into a `.dictionary` bundle.

Expected build flow:

```sh
cd {args.output_dir}
make
make install
```

If the DDK is not in the default Xcode path, pass it explicitly:

```sh
make DICT_BUILD_TOOL_DIR="/path/to/Dictionary Development Kit"
```

After install, open Dictionary.app and enable the dictionary in Settings.
""",
        encoding="utf-8",
    )


def parse_args():
    parser = argparse.ArgumentParser(description="Build Apple Dictionary DDK source files from generated entries.")
    parser.add_argument("--entries-dir", type=Path, default=Path("outputs/entries-oxford5000"))
    parser.add_argument("--wordforms", type=Path, default=Path("data/lemma-wordforms.csv"))
    parser.add_argument(
        "--index-mode",
        choices=["headword", "wordforms"],
        default="headword",
        help="Use only each entry headword as an index, or also index stored wordforms.",
    )
    parser.add_argument("--output-dir", type=Path, default=Path("build/apple-dictionary"))
    parser.add_argument("--dict-name", default=DEFAULT_DICT_NAME)
    parser.add_argument("--package-name", default=DEFAULT_PACKAGE_NAME)
    parser.add_argument("--display-name", default="概念英汉词典")
    parser.add_argument("--bundle-id", default=DEFAULT_BUNDLE_ID)
    parser.add_argument("--version", default=DEFAULT_VERSION)
    parser.add_argument("--manufacturer", default="Open Concept Dictionary Project")
    parser.add_argument("--copyright", default="Generated dictionary data. Review before redistribution.")
    parser.add_argument("--xml-name", default="ConceptDictionary.xml")
    parser.add_argument("--limit", type=int, help="Generate only the first N entries for smoke tests.")
    parser.add_argument("--clean", action="store_true", help="Remove output directory before generating.")
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
    write_makefile(args.output_dir / "Makefile", args)
    write_readme(args.output_dir / "README.md", args)

    print(f"entries={len(entries)}")
    print(f"index_mode={args.index_mode}")
    print(f"xml={xml_path}")
    print(f"output_dir={args.output_dir}")


if __name__ == "__main__":
    main()
