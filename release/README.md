# Deep Dict Release

This directory contains local release artifacts for Deep Dict.

## Files

- `DeepDict.dictionary.zip`: installable macOS Dictionary.app bundle archive.
- `included-words.csv`: included headword list from the final run.
- `qa-summary.json`: confidence and QA summary from the final run.
- `entries-merged-clean.tar.zst`: compressed generated entry JSON archive.
- `SHA256SUMS`: checksums for release artifacts.

## Install

Extract `DeepDict.dictionary.zip`, then copy `DeepDict.dictionary` into:

```sh
~/Library/Dictionaries/
```

Open Dictionary.app and enable `Deep Dict` in settings.
