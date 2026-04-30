# Deep Dict

[English README](README.en.md)

Deep Dict 是一个面向 macOS Dictionary.app 与系统 Lookup 功能的英汉词典。它主要服务于需要长期阅读英语内容的中文母语者，目标是在尽量减少阅读中断的前提下，提供简洁、直接、易于快速理解的中文释义。

词条由 DeepSeek V4 Pro 批量生成。当前版本共生成 100,683 条候选词条，其中 91,813 条进入最终词典；整个生成过程约消耗 2.57 亿个 token。

## 安装

解压 `release/DeepDict.dictionary.zip`，然后将 `DeepDict.dictionary` 复制到：

```sh
~/Library/Dictionaries/
```

之后打开 Dictionary.app，并在设置中启用 `Deep Dict`。

## 项目定位

Deep Dict 是阅读辅助型词典，不是百科全书，也不是完整的英语学习词典。它适合在阅读英文文章、论文、论坛和技术文档时快速确认词义，并在 macOS Lookup 弹窗中展示短而清晰的中文释义。

它不试图覆盖完整词源、音标、例句、搭配、语法说明，也不系统收录人物、机构、品牌、产品、事件等百科条目。

## 词库来源

候选词表由基础频率词表与公开语料补充构成。项目首先通过 word frequency 数据提取约 10 万个英语候选词，并清理其中明显不适合作为词典词条的项目；随后从 LessWrong、Hacker News 近两年内容，以及 Reddit 评论语料中抽取词汇，用来补充论坛、技术社区和现代日常讨论中更常见的表达；此外还保留了一个较小的核心英语词表，用于覆盖基础阅读词汇。

这些来源的目标不是穷尽英语词汇，而是覆盖真实阅读环境中更可能遇到、且具有查词价值的词。

## 收录标准

本词典并非百科全书，因此许多专有名词、品牌、产品、人名、公司名和事件名不会被收录。例如，`DeepSeek` 这类词并不一定会作为普通词条进入主词典，它们更适合由百科词典、Wikipedia、技术术语表或独立的专有名词词典处理。

收录时主要考虑：该词是否会影响普通英文阅读理解；模型是否能够可靠识别 exact 输入词；是否能够生成简洁、准确、适合中文读者快速理解的释义；该释义是否适合在 macOS Lookup 弹窗中展示。

常见、通用、对理解文本最有帮助的义项会优先出现；罕见义项通常不会被完整收录。

## 复现与构建

安装依赖并生成词条：

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export DEEPSEEK_API_KEY="..."
python scripts/generate_entries.py --workers 64
```

构建 macOS 词典需要 Apple Dictionary Development Kit：

```sh
python scripts/build_apple_dictionary_source.py --entries-dir outputs/entries-merged-clean --output-dir build/deep-dict --dict-name "Deep Dict" --package-name DeepDict --display-name "Deep Dict" --bundle-id org.deepdict.dictionary.en-zh --manufacturer "Deep Dict Project" --xml-name DeepDict.xml --clean
make -C build/deep-dict DICT_BUILD_TOOL_DIR="/path/to/Dictionary Development Kit"
make -C build/deep-dict install
```

## 仓库结构

- `prompts/entry-generation-system.md`：词条生成提示词。
- `scripts/`：词表提取、词条生成和 Apple Dictionary 构建脚本。
- `data/generation-targets/merged-clean/words.csv`：当前生产候选词表。
- `data/final-wordlists/included-words.csv`：最终收录词表。
- `release/`：当前发布产物。

## 开源说明

词条由 LLM 生成，不应被视为权威专业词典数据。正式开源发布前，仍需要明确代码、生成数据和 release artifact 的 license。
