"""Entry schema validation.

validate_entry() is the single definition of a valid entry JSON object. It
both checks and normalizes (POS aliases, whitespace, absent definition_zh).
"""

POS_VALUES = {
    "n.",
    "v.",
    "adj.",
    "adv.",
    "prep.",
    "pron.",
    "conj.",
    "interj.",
    "det.",
    "num.",
    "aux.",
    "modal",
    "prefix",
    "suffix",
}

POS_ALIASES = {
    "abbr.": "n.",
    "abbrev.": "n.",
    "abbreviation": "n.",
    "noun": "n.",
    "verb": "v.",
    "adjective": "adj.",
    "adverb": "adv.",
    "preposition": "prep.",
    "pronoun": "pron.",
    "conjunction": "conj.",
    "interjection": "interj.",
    "determiner": "det.",
    "number": "num.",
    "particle": "prep.",
    "infinitive marker": "prep.",
    "article": "det.",
    "art.": "det.",
    "contraction": "interj.",
    "phrase": "interj.",
}

EXCLUDE_REASONS = {
    "not_english_word",
    "misspelling_or_fragment",
    "nonstandard_contraction_spelling",
    "abbreviation_or_acronym",
    "proper_name_or_brand",
    "username_or_platform_artifact",
    "profanity_or_slur",
    "too_uncertain",
    "not_useful_for_reading",
}


def validate_score(data, key):
    value = data.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{key} must be an integer")
    if value < 0 or value > 10:
        raise ValueError(f"{key} must be between 0 and 10")
    return value


META_KEYS = ("model", "effort", "prompt", "generated", "edited", "edited_by")


def validate_meta(data):
    """meta records how an entry was produced. Optional; string values only."""
    meta = data.get("meta")
    if meta is None:
        return {}
    if not isinstance(meta, dict):
        raise ValueError("meta must be an object")
    for key, value in meta.items():
        if key not in META_KEYS:
            raise ValueError(f"unexpected meta key: {key!r}")
        if not isinstance(value, str) or not value:
            raise ValueError(f"meta.{key} must be a non-empty string")
    return {"meta": {key: meta[key] for key in META_KEYS if key in meta}}


def validate_entry(data, expected_word, protected_words=frozenset()):
    if not isinstance(data, dict):
        raise ValueError("entry must be a JSON object")
    meta = validate_meta(data)
    if data.get("word") != expected_word:
        raise ValueError(f"word mismatch: expected {expected_word!r}, got {data.get('word')!r}")
    include = data.get("include")
    if not isinstance(include, bool):
        raise ValueError("include must be a boolean")
    suitability_score = validate_score(data, "suitability_score")
    meaning_confidence = validate_score(data, "meaning_confidence")
    exclude_reason = data.get("exclude_reason")

    senses = data.get("senses")
    if not isinstance(senses, list):
        raise ValueError("senses must be an array")

    allowed_entry_keys = {
        "word",
        "include",
        "suitability_score",
        "meaning_confidence",
        "exclude_reason",
        "senses",
        "meta",
    }
    extra_entry_keys = set(data) - allowed_entry_keys
    if extra_entry_keys:
        raise ValueError(f"unexpected entry keys: {sorted(extra_entry_keys)}")

    if include:
        if exclude_reason is not None:
            raise ValueError("exclude_reason must be null when include is true")
        if meaning_confidence <= 4:
            raise ValueError("include=true requires meaning_confidence > 4")
        if not senses:
            raise ValueError("senses must be a non-empty array when include is true")
    else:
        if expected_word.lower() in protected_words:
            raise ValueError(f"protected word was excluded: {expected_word}")
        if exclude_reason not in EXCLUDE_REASONS:
            raise ValueError(f"invalid exclude_reason: {exclude_reason!r}")
        if senses:
            raise ValueError("senses must be empty when include is false")
        return {
            "word": data["word"],
            "include": False,
            "suitability_score": suitability_score,
            "meaning_confidence": meaning_confidence,
            "exclude_reason": exclude_reason,
            "senses": [],
            **meta,
        }

    required_sense_keys = {"pos", "context_label", "gloss_zh"}
    optional_sense_keys = {"definition_zh"}
    allowed_sense_keys = required_sense_keys | optional_sense_keys
    for idx, sense in enumerate(senses, 1):
        if not isinstance(sense, dict):
            raise ValueError(f"sense {idx} must be an object")
        keys = set(sense)
        missing = required_sense_keys - keys
        extra = keys - allowed_sense_keys
        if missing:
            raise ValueError(f"sense {idx} missing keys: {sorted(missing)}")
        if extra:
            raise ValueError(f"sense {idx} has unexpected keys: {sorted(extra)}")

        pos = str(sense["pos"]).strip()
        pos = POS_ALIASES.get(pos.lower(), pos)
        if pos not in POS_VALUES:
            raise ValueError(f"sense {idx} has invalid pos: {pos!r}")
        sense["pos"] = pos

        context_label = sense["context_label"]
        if not isinstance(context_label, str):
            raise ValueError(f"sense {idx} context_label must be a string")
        if context_label.count("/") >= 3:
            raise ValueError(f"sense {idx} context_label has too many labels")

        value = sense["gloss_zh"]
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"sense {idx} gloss_zh must be a non-empty string")

        # A non-string definition_zh (commonly null, when the model has no
        # extra explanation to add) is treated as absent rather than an error.

    return {
        "word": data["word"],
        "include": True,
        "suitability_score": suitability_score,
        "meaning_confidence": meaning_confidence,
        "exclude_reason": None,
        "senses": [
            ({
                "pos": sense["pos"].strip(),
                "context_label": sense["context_label"].strip(),
                "gloss_zh": sense["gloss_zh"].strip(),
            } | (
                {"definition_zh": sense["definition_zh"].strip()}
                if isinstance(sense.get("definition_zh"), str) and sense["definition_zh"].strip()
                else {}
            ))
            for sense in senses
        ],
        **meta,
    }
