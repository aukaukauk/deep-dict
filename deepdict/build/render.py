"""Apple Dictionary DDK source rendering.

Ported from the v1 build script. Output is one <d:entry> per included entry:
headword, optional inflected-form indexes, and the ordered sense list.
"""

import json
from html import escape
from pathlib import Path

from ..ids import stable_id

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


def load_entries(input_dir, limit=None):
    entries = []
    for path in sorted(Path(input_dir).glob("*.json")):
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
    <p>英汉阅读词典，词条由 LLM 生成。</p>
    <p>Entries: {entry_count}</p>
  </d:entry>'''


def write_xml(path, entries, forms_by_word, dict_name):
    with Path(path).open("w", encoding="utf-8", newline="\n") as f:
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


CSS_TEXT = """body {
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
"""


def write_css(path):
    Path(path).write_text(CSS_TEXT, encoding="utf-8")
