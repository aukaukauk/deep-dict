"""Canonical stable id for headwords.

NFKD-normalizes the headword before slugging. This id names every entry
file (w_<id>.json) and every <d:entry>, so it must never change.
"""

import hashlib
import re
import unicodedata


def stable_id(word):
    normalized = unicodedata.normalize("NFKD", word)
    ascii_word = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    slug = re.sub(r"[^A-Za-z0-9]+", "_", ascii_word).strip("_").lower()
    if not slug:
        digest = hashlib.sha1(word.encode("utf-8")).hexdigest()[:10]
        slug = f"x_{digest}"
    return f"w_{slug}"
