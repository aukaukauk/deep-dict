"""MDict (.mdx) writer and reader, on top of the mdict-utils package.

mdict-utils packs from a text source of the form

    headword
    <article html on one line>
    </>

so write_mdx() writes that source file first and then packs it.
"""

from pathlib import Path


def write_mdx(mdx_path, source_path, articles, title, description):
    """articles: iterable of (word, html); html must not contain newlines."""
    from mdict_utils.writer import MDictWriter, pack_mdx_txt

    source_path = Path(source_path)
    source_path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with source_path.open("w", encoding="utf-8", newline="\n") as f:
        for word, html in articles:
            if "\n" in word or "\n" in html:
                raise ValueError(f"newline in MDX article: {word!r}")
            f.write(f"{word}\n{html}\n</>\n")
            count += 1

    dictionary = pack_mdx_txt(str(source_path), encoding="UTF-8")
    if len(dictionary) != count:
        raise ValueError(f"MDX source parsed to {len(dictionary)} articles, expected {count}")
    writer = MDictWriter(dictionary, title=title, description=description, encoding="UTF-8")
    with Path(mdx_path).open("wb") as f:
        writer.write(f)
    return count


def read_mdx(mdx_path):
    """Yield (word, html). Used to verify a written dictionary."""
    from mdict_utils.reader import MDX

    for key, value in MDX(str(mdx_path)).items():
        yield key.decode("utf-8"), value.decode("utf-8").rstrip("\r\n\0")
