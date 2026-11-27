"""ECDICT cross-checking.

ECDICT (work/vendor/ecdict/ecdict.csv, ~770k headwords with Chinese translations)
is an independent evidence source for two signals:

- existence: a rare word that ECDICT has never heard of is weak evidence the
  headword itself is noise (or that the model had nothing to recall from);
- gloss corroboration: the generated gloss_zh should share at least some
  content characters with ECDICT's translation. Zero overlap on a word ECDICT
  does know is a strong fabricated-sense signal.

The comparison is deliberately loose (CJK character overlap): DeepDict
glosses are rewritten for reading, so only contradiction is meaningful,
not divergence.
"""

import csv
import sys


def load_translations(path):
    csv.field_size_limit(sys.maxsize)
    translations = {}
    with open(path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            word = (row.get("word") or "").strip().lower()
            if not word:
                continue
            translation = (row.get("translation") or "").strip()
            if word not in translations or len(translation) > len(translations[word]):
                translations[word] = translation
    return translations


def cjk_chars(text):
    return {
        ch
        for ch in text or ""
        if "一" <= ch <= "鿿" or "㐀" <= ch <= "䶿"
    }


def entry_gloss_chars(entry):
    chars = set()
    for sense in entry.get("senses", []):
        chars |= cjk_chars(sense.get("gloss_zh", ""))
    return chars


def gloss_overlap(entry, translation):
    """Fraction of the entry's gloss CJK characters that also appear in the
    ECDICT translation. Returns None when either side has no CJK content."""
    gloss = entry_gloss_chars(entry)
    reference = cjk_chars(translation)
    if not gloss or not reference:
        return None
    return sum(1 for ch in gloss if ch in reference) / len(gloss)
