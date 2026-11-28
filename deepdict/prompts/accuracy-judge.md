# Task: judge dictionary entries against reference dictionaries

You are checking entries of an English-Chinese dictionary (LLM-generated) against
authoritative references. Read your batch file, judge every word in it, and write
one JSON file with your verdicts. Do not use the web or any other source: judge
only from the batch file plus your own knowledge of English.

## About the dictionary being checked

- It is a reading aid: for each word it lists the few senses a reader is most
  likely to meet, each with a short Chinese gloss (`gloss_zh`) and usually a
  one-sentence Chinese explanation (`explanation_zh`).
- It deliberately lists only a few senses and omits examples and etymology.
  **A missing sense is never a defect, even when the missing sense is the one a
  reader would meet most often.** Judge only what the entry states.
- Inflected forms (plurals, past tenses, -ing forms) are separate entries and are
  explained as that form. That is by design.
- It also contains some proper names, brand names, foreign words and internet
  slang. Glossing a name as a name is fine.
- Senses from modern or technical usage that learner dictionaries do not list are
  fine if they are real.
- **Proper names are glossed by category only**: the gloss is 人名, 地名, 机构名,
  品牌名, 作品名 or 角色名, with no transliteration. An explanation is optional and,
  when present, starts with 可指 and names one or more common referents. A bare
  category with no explanation is acceptable. Judge whether the word really is
  used as that kind of name and whether any referent stated is real and
  correctly described. Do not downgrade for a neighbouring category (a fictional
  character labelled 人名, a company labelled 品牌名).
- Offensive words are defined plainly with a register label such as 粗俗 or 蔑称.
  That is by design; judge only whether the meaning and label are accurate.

## The references

Each item has `reference` with up to three sources, any of which may be null:
`cambridge_english_chinese` (English definition — Chinese translation),
`cambridge_english`, `american_heritage`. For an inflected word the reference
shown may be for its base form (see `headword`); judge the meaning accordingly.

## Verdicts

Give each word exactly one `verdict`:

- `correct` — the word is correctly identified, every listed sense is a real
  sense of this word, and the Chinese gloss and explanation are accurate.
- `minor` — the main meaning is right, but something is off: a gloss that is
  imprecise, too narrow or too broad for the sense it describes; a wrong part
  of speech; a misleading label; or a doubtful secondary sense.
- `wrong` — a reader would be misled: the word is misidentified (for example
  confused with a similar-looking word), or the primary sense is wrong, or a
  listed sense is invented or contradicted by the references.
- `unverifiable` — the references do not cover the word and you cannot confirm
  or refute the entry from your own knowledge with confidence.

Be strict but fair. Do not downgrade an entry for style, for brevity, or for
omitting senses. Do downgrade it when a Chinese gloss would give
the reader the wrong idea. If the references are null, judge from your own
knowledge; if you are not confident, use `unverifiable` rather than guessing.

## Output

Write a JSON array, one object per word, in the same order as the batch:

```json
{
  "word": "token",
  "ref_coverage": "found",
  "verdict": "correct",
  "basis": "reference",
  "problem": ""
}
```

- `ref_coverage`: `found` (a reference covers this word or its base form),
  or `none` (all references are null).
- `basis`: `reference` if the references were enough to decide, `own_knowledge`
  if you had to rely on what you know (always the case when `ref_coverage` is
  `none`, and also when the entry's senses go beyond what the references list).
- `problem`: empty for `correct`. Otherwise one or two sentences **in Chinese**
  saying exactly what is wrong and, where possible, what it should be. For
  `unverifiable`, say briefly why.

Every word in the batch must appear exactly once. Write valid JSON (UTF-8, no
comments, no trailing commas) to the output path you were given, then reply with
only the counts per verdict.
