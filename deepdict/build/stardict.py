"""StarDict writer and a minimal reader.

A StarDict dictionary is three files:
  .ifo   plain-text metadata
  .idx   sorted index: word (UTF-8) + NUL + offset (u32 BE) + size (u32 BE)
  .dict  the article data, concatenated

Readers binary-search the index, so it must be sorted the way StarDict
compares words: ASCII-case-insensitively first, then by raw bytes.
"""

import struct
import zipfile
from pathlib import Path


def sort_key(word):
    raw = word.encode("utf-8")
    folded = bytes(c + 32 if 65 <= c <= 90 else c for c in raw)
    return (folded, raw)


def write_stardict(out_dir, name, articles, bookname, description, author):
    """articles: iterable of (word, html). Returns the three written paths."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    items = sorted(articles, key=lambda item: sort_key(item[0]))

    dict_path = out_dir / f"{name}.dict"
    idx_path = out_dir / f"{name}.idx"
    ifo_path = out_dir / f"{name}.ifo"

    offset = 0
    with dict_path.open("wb") as dict_f, idx_path.open("wb") as idx_f:
        for word, html in items:
            data = html.encode("utf-8")
            dict_f.write(data)
            idx_f.write(word.encode("utf-8") + b"\0" + struct.pack(">II", offset, len(data)))
            offset += len(data)

    ifo_lines = [
        "StarDict's dict ifo file",
        "version=2.4.2",
        f"bookname={bookname}",
        f"wordcount={len(items)}",
        f"idxfilesize={idx_path.stat().st_size}",
        f"author={author}",
        f"description={description}",
        "sametypesequence=h",
    ]
    ifo_path.write_text("\n".join(ifo_lines) + "\n", encoding="utf-8")
    return [ifo_path, idx_path, dict_path]


def read_stardict(directory, name):
    """Yield (word, html) in index order. Used to verify a written dictionary."""
    directory = Path(directory)
    idx = (directory / f"{name}.idx").read_bytes()
    data = (directory / f"{name}.dict").read_bytes()
    pos = 0
    while pos < len(idx):
        end = idx.index(b"\0", pos)
        word = idx[pos:end].decode("utf-8")
        offset, size = struct.unpack(">II", idx[end + 1:end + 9])
        pos = end + 9
        yield word, data[offset:offset + size].decode("utf-8")


def zip_files(zip_path, paths, folder):
    """Deterministic zip (fixed timestamps) of paths under one folder name."""
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for path in sorted(paths):
            info = zipfile.ZipInfo(f"{folder}/{Path(path).name}", date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            zf.writestr(info, Path(path).read_bytes())
