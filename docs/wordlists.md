# 候选词表来源

候选词表决定哪些词会被送去生成。所有词表都在 `data/generation-targets/<来源>/words.csv`，只有一列 `word`。

## 各来源

| 来源 | 词数 | 说明 | 构建模块 |
| --- | --- | --- | --- |
| `oxford5000` | 4,944 | 核心英语词表 | `build_oxford5000_tables` |
| `wordfreq-r100000-clean` | 95,662 | wordfreq 前 10 万词，清理后 | `build_wordfreq_wordlist`、`clean_wordfreq_top` |
| `lesswrong` | 19,226 | LessWrong 全站语料中的补充词 | `build_lesswrong_wordlist` |
| `hacker-news` | 8,079 | Hacker News 2024–2025 的补充词 | `build_hacker_news_wordlist` |
| `reddit-comments` | 1,740 | Reddit 评论语料的补充词 | `build_reddit_wordlist` |
| `merged-clean` | 100,683 | 以上合并去重，V1 的生成输入 | `merge_generation_targets`、`dedupe_generation_targets` |
| `cogsci-academic` | 6,196 | 认知科学及相关学科术语，V2 新增 | `build_cogsci_wordlist` |

构建模块都在 `deepdict/wordlists/` 下，用 `.venv/bin/python -m deepdict.wordlists.<模块名> --help` 查看参数。

社区语料类词表的做法是：从语料里统计词频，去掉核心词表里已有的词，再用 ECDICT 和大小写比例过滤掉明显的噪声。

学术词表的细节见 [cogsci-source.md](cogsci-source.md)。

## 关于这些构建模块

除了 `build_cogsci_wordlist`，其余模块是 V1 时期写的，现在主要作为词表出处的记录保留：

- 它们需要的原始语料（如 `data/raw/lesswrong_full.json`）和一些中间文件不在仓库里。
- 部分默认路径指向已经不存在的早期文件。
- 搬进 `deepdict/` 包时只改了导入方式，没有重新跑过完整流程。

其中 `extract_ecdict_wordforms`、`extract_lemma_wordforms`、`filter_ecdict_main_words`、`build_surface_word_targets`、`plan_current_lexicon_cleanup`、`analyze_lesswrong_coverage` 从默认路径看属于更早的一条思路（以 ECDICT 词元为基础），应该没有用在最终的生产词表上。

## 收录策略

词表本身尽量宽松，筛选交给生成步骤：模型会排除明显的噪声、碎片、拼写不确定的词，以及它无法可靠识别的词。屈折变化、复数、常见人名地名、现代技术词，只要模型能高置信地解释，一般都保留。
