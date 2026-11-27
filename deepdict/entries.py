"""Entry IO helpers.

Entries live as one JSON file per word, named by deepdict.ids.stable_id.
iter_entries() reads either an extracted directory or a .tar.zst archive
(streamed through the zstd binary), so analysis passes do not require an
extracted tree.
"""

import csv
import json
import subprocess
import tarfile
import tempfile
from pathlib import Path


def iter_entries(source):
    source = Path(source)
    if source.is_dir():
        for path in sorted(source.glob("*.json")):
            with path.open("r", encoding="utf-8") as f:
                yield json.load(f)
        return
    if source.name.endswith(".tar.zst"):
        proc = subprocess.Popen(["zstd", "-dc", str(source)], stdout=subprocess.PIPE)
        try:
            with tarfile.open(fileobj=proc.stdout, mode="r|") as tar:
                for member in tar:
                    if not member.isfile() or not member.name.endswith(".json"):
                        continue
                    f = tar.extractfile(member)
                    if f is None:
                        continue
                    yield json.loads(f.read().decode("utf-8"))
        finally:
            proc.stdout.close()
            proc.wait()
        return
    raise ValueError(f"unsupported entries source: {source}")


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
