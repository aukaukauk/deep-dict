# 候选词表

这个目录回答一个问题：词典里收哪些词。

每个 `.csv` 是一个来源的候选词表，只有一列 `word`。`build/` 里是提取它们的脚本。候选词表只决定哪些词被送去生成，最终是否收录由生成步骤里的模型判断。

## 各来源

| 文件 | 词数 | 来源 | 提取脚本 |
| --- | --- | --- | --- |
| `wordfreq.csv` | 95,662 | wordfreq 词频表的前 10 万词，清理后 | `build_wordfreq_wordlist.py`、`clean_wordfreq_top.py` |
| `oxford5000.csv` | 4,944 | Oxford 5000 核心词表 | `build_oxford5000_tables.py` |
| `lesswrong.csv` | 19,226 | LessWrong 全站文章 | `build_lesswrong_wordlist.py` |
| `hacker-news.csv` | 8,079 | Hacker News 的帖子和评论 | `build_hacker_news_wordlist.py` |
| `reddit.csv` | 1,740 | Reddit 评论 | `build_reddit_wordlist.py` |
| `merged.csv` | 100,683 | 以上五个合并去重 | `merge_generation_targets.py` |
| `cogsci/words.csv` | 6,196 | 认知科学及相关学科的术语 | `build_cogsci_wordlist.py` |
| `ecdict-tagged.csv` | 708 | ECDICT 里带考试或学习词表标注、而上面没有的词 | `build_expansion_candidates.py` |
| `contractions.csv` | 774 | wordfreq 里带撇号的缩约形式，如 it's、o'clock | `build_expansion_candidates.py` |
| `wordfreq-rest.csv` | 187,276 | wordfreq 里其余全部纯字母词，按词频从高到低 | `build_expansion_candidates.py` |
| `new-words.csv` | 2,821 | 近几年的新词，由几个大模型分领域列出 | 没有脚本，提示词见 `build/new-words-prompt.md` |

送去生成的是 `merged.csv`、`cogsci/words.csv` 和后四个扩充词表，合计 298,458 个词。

## 两个阶段

**最初的 106,879 个词**（`merged.csv` 和 `cogsci/words.csv`）是先筛后生成的：按词频截取前 10 万，再用规则去掉缩写、专有名词和噪声。

**2026 年 11 月扩充的 188,758 个词**（`ecdict-tagged.csv`、`contractions.csv`、`wordfreq-rest.csv`）不再预先筛选。wordfreq 的 32 万词条里，只有机械规则能判定的才去掉：含数字或符号的、带非 ASCII 字母的、所有格形式。其余的全部送去生成，由模型判断是否收录。原因是预先筛选会误伤，最初那批里就有 romantic、purple、burden 这样的常用词被筛掉。

扩充之后，wordfreq 的全部纯字母词都经过了模型判断，没有再按词频截断。

**近几年的新词**（`new-words.csv`）是另一种来源。wordfreq 的数据止于 2021 年前后，之后出现的词它都没有，例如 chatgpt、mpox、shrinkflation。这批候选不是从语料里统计出来的，而是让几个大模型按 15 个领域回忆、列出新词，合并去重后得到的：

| 来源 | 列出的候选数 |
| --- | --- |
| 一个未记名的模型 | 2,086 |
| Claude | 744 |
| Gemini | 678 |
| DeepSeek | 102 |

其中 765 个词被两个以上的来源列出，所以各行相加超过 2,821。每个词由谁列出记在 `new-words-sources.csv` 里。提示词、处理步骤和这种做法的不足，见 `build/new-words-prompt.md`。

## 合并

`merged.csv` 按下面的顺序合并，后面的来源只补充前面没有的词：

| 顺序 | 来源 | 新增词数 |
| --- | --- | --- |
| 1 | wordfreq | 95,662 |
| 2 | oxford5000 | 21 |
| 3 | lesswrong | 2,442 |
| 4 | hacker-news | 2,433 |
| 5 | reddit | 125 |

词频表提供了主体，社区语料补的是词频表里排不进前 10 万、但在这些社区里常见的词。

## 提取方法

**词频表。** 从 wordfreq 按频率取词，去掉含数字或符号的、非 ASCII 的和单字母噪声。再做一轮清理，去掉缩约形式的无撇号拼写（如 dont）、网络缩写（如 lol、imo）、首字母缩写、非词和标记出的脏话。最终词表里只有纯字母词。

**社区语料**（LessWrong、Hacker News、Reddit）。三个脚本共用一套逻辑：

1. 把正文切成词，统计每个词的出现次数和出现在多少篇文档里。
2. 去掉核心词表里已有的词，以及它们的屈折变化形式。
3. 用大小写比例去掉看起来像专有名词、品牌或首字母缩写的词。
4. 按出现次数和文档数设门槛。ECDICT 收录的词门槛低，没收录的词门槛高。

**学术词表。** 来自四类公开资源，全部是结构化数据，不消耗 token：

| 来源 | 用途 |
| --- | --- |
| Wikipedia 的术语表和索引页 | 神经科学、AI、计算机、哲学、心理学、统计等学科的人工编纂术语 |
| Wiktionary 的学科分类 | 按学科归类的词条 |
| arXiv 摘要（cs.AI、cs.LG、cs.CL、q-bio.NC） | 按文档频率补充活跃术语 |
| 斯坦福哲学百科目录 | 哲学词条标题 |

抽出的词与 `merged.csv` 做差集，只保留新词。

`cogsci/` 里除了 `words.csv`，还有几份没有送去生成的表：

| 文件 | 内容 |
| --- | --- |
| `words-compound.csv` | 2,293 个连字符复合词，如 trade-off |
| `words-arxiv.csv` | 311 个只在 arXiv 出现的词，可信度较低 |
| `phrases.csv` | 7,479 个多词术语 |
| `provenance.csv` | 每个候选词的出处：学科、来源、是否在 ECDICT 里、词频 |

学术词表里有可以预见的噪声，比如 Wiktionary 收的网络新词、人名衍生词和缩写。这些没有在提取时过滤，因为罕见的学术词和噪声在词频上分不开，留给生成步骤去排除。

## 运行脚本

脚本在仓库根目录运行，例如：

```sh
.venv/bin/python wordlists/build/merge_generation_targets.py --help
```

需要说明的几点：

- **能直接重跑的有三个。** `merge_generation_targets.py` 和 `build_cogsci_wordlist.py --build` 在当前仓库里重跑过，输出与这里的文件完全一致。`build_expansion_candidates.py` 需要 wordfreq 包和 ECDICT；它只列出词典里还没有记录的词，所以在扩充完成后的仓库里重跑会得到空表。
- **其余脚本没有重新跑过。** 它们需要的原始语料不在仓库里（如 LessWrong 的全站导出），搬到这个目录时只改了默认路径。上面"提取方法"是按代码逻辑写的，表里没有列出当时实际使用的参数。
- **三个辅助脚本**为社区语料脚本准备输入：`extract_ecdict_wordforms.py` 和 `extract_lemma_wordforms.py` 生成词形表，`filter_ecdict_main_words.py` 生成清洗过的 ECDICT 词表。
- `dedupe_generation_targets.py` 按优先级在各来源之间去重，会直接改写词表文件，运行前先加 `--dry-run`。
- 中间产物默认写到 `work/wordlist-builds/`，ECDICT 默认在 `work/vendor/ecdict/ecdict.csv`。
- Hacker News 和 Reddit 的脚本需要额外的包：`.venv/bin/pip install -e ".[wordlists]"`。
