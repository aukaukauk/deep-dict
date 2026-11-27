"""Portable entry HTML for dictionary formats that have no shared stylesheet.

MDict and StarDict readers differ in how (and whether) they load external
CSS, and many have a dark theme. So this markup carries its few styles
inline and uses only colors that stay legible on both light and dark
backgrounds; body text keeps the reader's own color.
"""

from html import escape

POS_STYLE = "color:#888;font-family:monospace"
LABEL_STYLE = "color:#4a7ab5"
HEAD_STYLE = "font-size:1.25em;font-weight:bold;margin:0 0 .35em"
LIST_STYLE = "margin:0;padding-left:1.5em"
ITEM_STYLE = "margin:.3em 0"
DEF_STYLE = "opacity:.8"


def sense_html(sense):
    pos = sense.get("pos", "").strip()
    context = sense.get("context_label", "").strip()
    gloss = sense.get("gloss_zh", "").strip()
    definition = sense.get("definition_zh", "").strip()

    bits = [f'<li style="{ITEM_STYLE}">']
    if pos:
        bits.append(f'<span style="{POS_STYLE}">{escape(pos)}</span> ')
    if context:
        bits.append(f'<span style="{LABEL_STYLE}">{escape(context)}</span> ')
    bits.append(f"<b>{escape(gloss)}</b>")
    if definition:
        bits.append(f'<div style="{DEF_STYLE}">{escape(definition)}</div>')
    bits.append("</li>")
    return "".join(bits)


def entry_html(entry, with_headword):
    """One entry as a single line of HTML (no newlines, so line-based
    source formats can carry it)."""
    parts = []
    if with_headword:
        parts.append(f'<div style="{HEAD_STYLE}">{escape(entry["word"])}</div>')
    parts.append(f'<ol style="{LIST_STYLE}">')
    parts.extend(sense_html(sense) for sense in entry["senses"])
    parts.append("</ol>")
    return "".join(parts)
