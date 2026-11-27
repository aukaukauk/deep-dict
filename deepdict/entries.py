"""Entry IO helpers.

Entries exist in two shapes:

  - the archive, dictionary/entries.jsonl.gz: one JSON object per line,
    every record (included and excluded), sorted by headword;
  - the working directory, work/entries/: one pretty-printed JSON file per
    word, named by deepdict.ids.stable_id. Pipeline steps read and write
    this directory.

iter_entries() reads either. pack_entries() / unpack_entries() convert
between them.
"""

import csv
import gzip
import json
import tempfile
from pathlib import Path

from .ids import stable_id


def entry_sort_key(entry):
    return (entry["word"].casefold(), entry["word"])


def iter_entries(source):
    source = Path(source)
    if source.is_dir():
        for path in sorted(source.glob("*.json")):
            with path.open("r", encoding="utf-8") as f:
                yield json.load(f)
        return
    if source.name.endswith(".jsonl.gz"):
        with gzip.open(source, "rt", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    yield json.loads(line)
        return
    if source.name.endswith(".jsonl"):
        with source.open("r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    yield json.loads(line)
        return
    raise ValueError(f"unsupported entries source: {source}")


def pack_entries(entries_dir, archive_path):
    """Write every entry in entries_dir to a .jsonl.gz archive. The output is
    deterministic: sorted by headword, no timestamp in the gzip header."""
    entries = sorted(iter_entries(entries_dir), key=entry_sort_key)
    archive_path = Path(archive_path)
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    with archive_path.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=9, mtime=0) as gz:
            for entry in entries:
                line = json.dumps(entry, ensure_ascii=False, separators=(",", ":"))
                gz.write(line.encode("utf-8") + b"\n")
    return entries


def unpack_entries(archive_path, entries_dir):
    """Expand an archive into one JSON file per word."""
    entries_dir = Path(entries_dir)
    entries_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    for entry in iter_entries(archive_path):
        path = entries_dir / f"{stable_id(entry['word'])}.json"
        with path.open("w", encoding="utf-8") as f:
            json.dump(entry, f, ensure_ascii=False, indent=2)
            f.write("\n")
        count += 1
    return count


def load_word_column(path):
    words = []
    with Path(path).open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if "word" not in (reader.fieldnames or []):
            raise ValueError(f"{path} must contain a 'word' column")
        for row in reader:
            word = (row.get("word") or "").strip()
            if word:
                words.append(word)
    return words


def write_json_atomic(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=str(path.parent),
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as f:
        tmp_path = Path(f.name)
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    tmp_path.replace(path)
