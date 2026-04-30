# Deep Dict

Deep Dict 是一个面向 macOS Dictionary.app 和三指取词 Lookup 的英汉词典。

它主要为需要经常阅读英语内容的中文母语者设计。它的核心目标不是像传统学习型词典那样系统讲解英语，而是尽量不打断阅读状态：用户扫一眼就能知道这个词在当前文本里大概是什么意思，然后继续读下去。

English version follows below.

## 当前版本

当前发布版本包含：

- 91,813 个已收录词条
- 8,870 个由模型判断不适合收录的候选词
- 最终生成批次中 0 个错误记录

可安装版本在：

- `release/DeepDict.dictionary.zip`

## 安装

解压 `release/DeepDict.dictionary.zip`，然后把 `DeepDict.dictionary` 复制到：

```sh
~/Library/Dictionaries/
```

打开 Dictionary.app，在设置里启用 `Deep Dict`。

## 这个词典适合谁

Deep Dict 更像一个阅读辅助工具，而不是百科全书或英语教材。

它适合：

- 阅读英文文章、论文、论坛、文档时快速扫词义；
- 希望 Lookup 弹窗尽量短、不挡住阅读节奏；
- 中文母语者需要快速理解英文词，而不是系统学习词源、例句和搭配。

它不适合：

- 替代专业学习词典；
- 查完整词源、发音、例句、搭配；
- 查百科条目、人物、品牌、公司、产品或事件。

## 词库来源

候选词表主要来自几类来源：

1. 通过 word frequency 数据提取约 10 万个英语候选词，并清理其中明显不需要的部分。
2. 从几个公开语料或数据集采样并提取高频词，包括：
   - LessWrong 论坛数据；
   - Hacker News 最近两年的内容；
   - 一个公开的 Reddit 评论数据集。
3. 额外保留了一个较小的核心英语词表，用来覆盖基础阅读词汇。

这些来源的目标不是穷尽英语，而是尽量覆盖真实阅读中容易遇到、又值得查的词。

## 收录标准

本词典不是百科全书。因此，很多专有名词、品牌、产品、人名、公司名和事件名不会被收录。

例如，`DeepSeek` 这类词本身就不一定会作为普通词条进入主词典。它更适合百科词典、Wikipedia、技术术语表或独立的专有名词词典。

收录时更看重：

- 这个词是否会影响普通英文阅读理解；
- 模型是否能可靠识别 exact 输入词；
- 是否能给出简洁、准确、中文读者一眼能理解的释义；
- 是否适合作为 macOS Lookup 弹窗里的短词条。

不追求完整覆盖每个罕见义项。常见、通用、阅读中最有用的义项会优先放在前面。

## 技术细节

词条释义由 LLM 批量生成。最终工作流使用的是 DeepSeek V4 Pro，脚本默认模型名为 `deepseek-v4-pro`，并使用 non-thinking 模式。

选择 DeepSeek V4 Pro 的原因是：它在成本、输出质量、中文表达、JSON 结构化输出和大规模并发生成之间取得了比较好的平衡。DeepSeek API 也提供了较低的缓存命中输入价格，适合这种高重复系统提示词的大规模生成任务。

根据 DeepSeek 控制台在 2026-04-29 的用量截图，本次项目生成大约消耗了 $257,257,198$ tokens，约 $2.57$ 亿 tokens：

- 输入（命中缓存）：$223,709,184$ tokens
- 输入（未命中缓存）：$14,201,947$ tokens
- 输出：$19,346,067$ tokens

生成脚本会要求模型返回结构化 JSON，包括：

- `include`：是否收录；
- `suitability_score`：是否适合作为词典词条；
- `meaning_confidence`：模型对 exact 输入词释义准确性的自评；
- `exclude_reason`：不收录原因；
- `senses`：词性、语境标签、中文短释义和必要时的一句中文解释。

`scripts/build_apple_dictionary_source.py` 会跳过 `include=false` 的词，只把收录词构建进 macOS `.dictionary` 包。

## 仓库结构

- `prompts/entry-generation-system.md`：词条生成提示词。
- `scripts/generate_entries.py`：并行调用 DeepSeek-compatible API 生成词条 JSON。
- `scripts/build_apple_dictionary_source.py`：把词条 JSON 转成 Apple Dictionary Development Kit 源文件。
- `scripts/watch_and_build_deep_dict.py`：生成完成后自动构建词典的 watcher。
- `scripts/build_*_wordlist.py`：不同来源的词表提取脚本。
- `data/generation-targets/merged-clean/words.csv`：当前生产候选词表。
- `data/final-wordlists/included-words.csv`：最终收录词表。
- `release/`：当前发布产物。
- `docs/lexicon-source-plan.md`：词库来源和工作流说明。

## 重新生成词条

创建 Python 环境并安装依赖：

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

设置 DeepSeek-compatible API key：

```sh
export DEEPSEEK_API_KEY="..."
```

运行生成：

```sh
python scripts/generate_entries.py --workers 64
```

生成结果会写入：

- `outputs/entries-merged-clean`
- `outputs/errors-merged-clean`
- `outputs/runs-merged-clean`

## 构建 macOS 词典

编译 `.dictionary` 包需要 Apple Dictionary Development Kit。这个工具不随本仓库分发。

生成 DDK 源文件：

```sh
python scripts/build_apple_dictionary_source.py \
  --entries-dir outputs/entries-merged-clean \
  --output-dir build/deep-dict \
  --dict-name "Deep Dict" \
  --package-name DeepDict \
  --display-name "Deep Dict" \
  --bundle-id org.deepdict.dictionary.en-zh \
  --manufacturer "Deep Dict Project" \
  --xml-name DeepDict.xml \
  --clean
```

编译：

```sh
make -C build/deep-dict DICT_BUILD_TOOL_DIR="/path/to/Dictionary Development Kit"
```

安装：

```sh
make -C build/deep-dict install
```

## 开源说明

这个项目的目标是做一个实用、简洁、适合中文母语者阅读英文时使用的 macOS 词典。

词条由 LLM 生成，不应被视为权威专业词典。发布前仍需要明确代码、生成数据和 release artifact 的 license。

---

# Deep Dict

Deep Dict is an English-Chinese dictionary for macOS Dictionary.app and three-finger Lookup.

It is designed for native Chinese speakers who frequently read English. The main goal is not to teach English in the traditional learner-dictionary sense. The goal is to preserve reading flow: glance at the Lookup popup, understand the word well enough, and keep reading.

## Current Release

The current release contains:

- 91,813 included entries
- 8,870 model-excluded candidate words
- 0 generation error records in the final batch

The installable build is:

- `release/DeepDict.dictionary.zip`

## Installation

Extract `release/DeepDict.dictionary.zip`, then copy `DeepDict.dictionary` to:

```sh
~/Library/Dictionaries/
```

Open Dictionary.app and enable `Deep Dict` in settings.

## What This Dictionary Is For

Deep Dict is a reading aid, not an encyclopedia or a full English learning dictionary.

It is useful when you want to:

- quickly understand English articles, papers, forums, and documentation;
- keep Lookup entries short and visually scannable;
- get concise Chinese glosses without examples, etymology, or long usage notes.

It is not meant to replace:

- professional learner dictionaries;
- etymology, pronunciation, example, or collocation resources;
- encyclopedias for people, brands, companies, products, or events.

## Word Sources

The candidate word list was built from several sources:

1. A broad word-frequency extraction of about 100,000 English candidate words, followed by cleanup.
2. Frequency extraction from public corpora or datasets, including:
   - LessWrong forum data;
   - Hacker News content from the last two years;
   - a public Reddit comments dataset.
3. A smaller core English word list for basic reading coverage.

The goal is not to cover all of English. The goal is to cover words that are likely to appear in real reading and are useful enough to look up.

## Inclusion Policy

This dictionary is not an encyclopedia. Many proper nouns, brands, products, people, companies, and events are intentionally not included.

For example, a term like `DeepSeek` is not necessarily included as a normal dictionary entry. It is better handled by an encyclopedia, Wikipedia, a technical glossary, or a separate proper-noun dictionary.

The inclusion policy prioritizes:

- whether the word affects normal English reading comprehension;
- whether the model can reliably identify the exact input word;
- whether a concise and accurate Chinese gloss can be produced;
- whether the entry works well inside a small macOS Lookup popup.

The dictionary does not try to list every rare sense. Common and reading-relevant senses come first.

## Technical Details

Entries were generated in batch with an LLM. The final workflow used DeepSeek V4 Pro. The default script model is `deepseek-v4-pro`, running in non-thinking mode.

DeepSeek V4 Pro was chosen because it offered a practical balance of cost, output quality, Chinese writing quality, JSON-structured output, and high-volume parallel generation. DeepSeek's API pricing also makes cached repeated system prompts relatively economical for this kind of workload.

Based on the DeepSeek usage dashboard screenshot from 2026-04-29, this generation run used about $257,257,198$ tokens, or roughly 257M tokens:

- Cached input: $223,709,184$ tokens
- Uncached input: $14,201,947$ tokens
- Output: $19,346,067$ tokens

The generation script asks the model to return structured JSON with:

- `include`: whether to include the word;
- `suitability_score`: whether it is suitable as a dictionary entry;
- `meaning_confidence`: confidence that the exact input word was understood correctly;
- `exclude_reason`: reason for exclusion;
- `senses`: part of speech, context label, concise Chinese gloss, and an optional short Chinese explanation.

`scripts/build_apple_dictionary_source.py` skips entries where `include=false`, so excluded candidates remain auditable without entering the macOS dictionary.

## Repository Layout

- `prompts/entry-generation-system.md`: entry-generation prompt.
- `scripts/generate_entries.py`: parallel DeepSeek-compatible JSON entry generator.
- `scripts/build_apple_dictionary_source.py`: converts entry JSON into Apple Dictionary Development Kit source.
- `scripts/watch_and_build_deep_dict.py`: optional watcher that builds after generation finishes.
- `scripts/build_*_wordlist.py`: source-specific word-list extraction scripts.
- `data/generation-targets/merged-clean/words.csv`: production candidate word list.
- `data/final-wordlists/included-words.csv`: final included headword list.
- `release/`: current release artifacts.
- `docs/lexicon-source-plan.md`: source and workflow notes.

## Regenerate Entries

Create a Python environment and install dependencies:

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Set a DeepSeek-compatible API key:

```sh
export DEEPSEEK_API_KEY="..."
```

Run generation:

```sh
python scripts/generate_entries.py --workers 64
```

Generated files are written to:

- `outputs/entries-merged-clean`
- `outputs/errors-merged-clean`
- `outputs/runs-merged-clean`

## Build macOS Dictionary

Apple's Dictionary Development Kit is required to compile the `.dictionary` bundle. The DDK is not distributed with this repository.

Generate DDK source files:

```sh
python scripts/build_apple_dictionary_source.py \
  --entries-dir outputs/entries-merged-clean \
  --output-dir build/deep-dict \
  --dict-name "Deep Dict" \
  --package-name DeepDict \
  --display-name "Deep Dict" \
  --bundle-id org.deepdict.dictionary.en-zh \
  --manufacturer "Deep Dict Project" \
  --xml-name DeepDict.xml \
  --clean
```

Compile:

```sh
make -C build/deep-dict DICT_BUILD_TOOL_DIR="/path/to/Dictionary Development Kit"
```

Install locally:

```sh
make -C build/deep-dict install
```

## Open Source Note

This project aims to provide a practical, concise macOS dictionary for Chinese-native readers of English.

Entries are generated by an LLM and should not be treated as authoritative professional lexicographic data. The repository still needs explicit licenses for code, generated data, and release artifacts before a formal open-source release.
