# Cognitive-Science Academic Word Source

2026-06-12。为认知科学及其交叉学科(神经科学、心理学、计算机/AI、哲学、语言学、人类学、统计)收集学术词汇的新词源。完全由公开结构化资源构建,零 API token。

## 构建

```sh
.venv/bin/python -m deepdict.wordlists.build_cogsci_wordlist --fetch   # 下载原始源(缓存于 work/cogsci-raw/)
.venv/bin/python -m deepdict.wordlists.build_cogsci_wordlist --build   # 抽词、分档、与现有 10 万词池做差集
```

## 来源

| 来源 | 用途 |
| --- | --- |
| Wikipedia glossary/index 页面 | 神经科学、AI、CS、哲学、心理、统计等人工编纂术语表 |
| Wiktionary 学科分类 | en:Neuroscience / en:Psychology / en:Philosophy 等,词条级单词 |
| arXiv 摘要(cs.AI/cs.LG/cs.CL/q-bio.NC) | 按文档频率抽词,补活跃术语 |
| 斯坦福哲学百科(SEP)目录 | 哲学词条标题 |

抽出的单词与 `data/generation-targets/merged-clean/words.csv` 做差集,只保留**新增**词。多词术语单独留在 `phrases.csv`,不进 `words.csv`(现有词池基本是单词词典,10 万词里仅 20 个含连字符)。

## 输出(data/generation-targets/cogsci-academic/)

| 文件 | 内容 |
| --- | --- |
| `words.csv` | **核心层 6,196 词**:单词、来自人工编纂源。推荐的生成输入 |
| `words-compound.csv` | 2,293 个连字符复合词(如 trade-off、self-awareness),按词典惯例暂留 |
| `words-arxiv.csv` | 311 个仅见于 arXiv 的单词,低置信,opt-in |
| `phrases.csv` | 7,479 个多词术语,留待将来决定是否做多词词条 |
| `provenance.csv` | 全部候选的出处:tier / fields / sources / n_sources / in_ecdict / zipf |

核心层 6,196 词中 3,932 个(63%)是 ECDICT 都不收录的罕见学术词——正是交叉学科里查词价值最高的部分。各学科分布(以首要 field 计):语言学 ~2,000、哲学 ~1,600、心理学 ~1,150、神经科学 ~280、统计 ~230、CS ~500、AI ~180。

## 质量与防噪

核心层以真实学术词为主(parahippocampal、monosynaptic、verificationism、isogloss、platykurtosis),但有可预见的噪声口袋:
- 心理学混入少量俚语/人格类型(collywobbles、isfp);
- AI 层混入 Wiktionary 近期网络新词(slopocalypse、cogsucker);
- 含少量人名衍生词(wernicke、heschl)和缩写(mcmc、dwh)。

不在构建期硬过滤这些,因为罕见学术词与噪声在词频/ECDICT 上不可分(强行过滤会误杀大量真词)。**过滤交给生成 pass**:prompt 的 `too_uncertain`/`abbreviation_or_acronym`/`proper_name_or_brand`/`not_english_word` 排除项会挡掉大部分;残余幻觉由 QA pass(误读检测 + ECDICT 交叉核对)兜底。provenance.csv 保证任何一个词都能追到它从哪个学科、哪个源进来。

## 生成结果

核心层 6,196 词已全部生成(2026-06,Codex 订阅,v2 prompt):5,606 个收录,590 个被模型排除。词条已并入 `data/entries/deepdict-v2-entries.tar.zst`。

复合词层(`words-compound.csv`)、arXiv 层和多词术语都还没有生成。要纳入时,把对应的 csv 作为 `--words` 传给 `deepdict.cli.generate_entries_batch` 即可(见 docs/pipeline.md)。
