# Lexicon Source Plan

## Active Production Source

The current production candidate table is:

- `data/generation-targets/merged-clean/words.csv`

It contains a single `word` column and is the target used by
`scripts/generate_entries.py` by default.

The latest final included word list is:

- `data/final-wordlists/included-words.csv`

This file contains the headwords that survived LLM generation and exclusion.

## Candidate Sources

The merged production table was built from several source tables under
`data/generation-targets/`:

- `oxford5000/words.csv`: compact core English word list.
- `wordfreq-r100000-clean/words.csv`: broad cleaned frequency candidate pool.
- `lesswrong/words.csv`: LessWrong-derived supplement candidates.
- `hacker-news/words.csv`: Hacker News-derived supplement candidates.
- `reddit-comments/words.csv`: Reddit-derived supplement candidates.

Older raw or partially merged tables were removed from the release tree. If they
are needed again, regenerate them with the source-builder scripts instead of
treating them as production inputs.

## Entry Generation Workflow

`scripts/generate_entries.py` defaults to:

- input: `data/generation-targets/merged-clean/words.csv`
- entries: `outputs/entries-merged-clean`
- errors: `outputs/errors-merged-clean`
- run summaries: `outputs/runs-merged-clean`

The prompt requires the model to return:

- `include`: whether the word should enter the dictionary.
- `suitability_score`: 0-10 score for dictionary usefulness.
- `meaning_confidence`: 0-10 confidence that the exact input word was understood.
- `exclude_reason`: fixed reason when `include=false`.
- `senses`: non-empty only when `include=true`.

The inclusion policy is intentionally permissive. The model should exclude only
obvious noise, fragments, uncertain spellings, and words it cannot reliably
identify. Inflections, plurals, names, places, brands, products, and modern
technical terms should generally be kept if the model can explain them with high
confidence.

`scripts/build_apple_dictionary_source.py` skips generated JSON records where
`include=false`, so excluded words can remain as audit records without entering
the macOS dictionary.

## macOS Dictionary Build

The build script produces Apple Dictionary Development Kit source under
`build/deep-dict` and compiles it into:

- `build/deep-dict/objects/DeepDict.dictionary`

The installed local copy is:

- `~/Library/Dictionaries/DeepDict.dictionary`

The DDK itself is not redistributed. Local DDK copies and build outputs are
ignored by Git.

## Open Source Notes

The repository is structured so the source code, prompt, candidate word lists,
and final included word list can be published without generated build clutter.

Before public release, choose explicit licenses for:

- scripts and documentation
- generated dictionary data
- release artifacts

Also review redistribution constraints for any third-party source word lists.
