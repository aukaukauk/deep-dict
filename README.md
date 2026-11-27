# DeepDict

DeepDict 是一部给中文母语者读英文用的英汉词典。它的目标只有一个：读到不认识的词时，尽快在上下文里看懂，然后回去继续读。

词条由 LLM 批量生成。当前版本（V2）有 106,879 个候选词，其中 96,669 个进入词典，共 136,222 个义项。

目前的成品是 macOS 词典包，用于 Dictionary.app 和系统的"查询"（Lookup）弹窗。

## 它是什么样的词典

DeepDict 是阅读辅助词典，不是学习词典，也不是百科全书。

- **释义以解释为主。** 只给一串近义翻译（如 serious＝严重的；严肃的；认真的）等于把辨义留给读者。V2 中 97% 的义项带一句话解释，说明这个词在这个意思下到底指什么。
- **义项按真实阅读频率排序和裁剪。** 平均每个词 1.4 个义项，罕见义项通常不收。
- **不收例句、音标、词源、搭配和用法说明。** 这些对"读懂当前这句"没有帮助，只会增加弹窗长度。
- **不系统收录专有名词。** 人物、机构、品牌、产品、事件更适合查百科。

<img src="assets/sample-token.png" alt="DeepDict Lookup 示例：token" width="520">

## 安装

`release/` 目录里是 V1 的安装包（2026 年 4 月，91,813 词）。解压 `release/DeepDict.dictionary.zip`，把 `DeepDict.dictionary` 复制到：

```sh
~/Library/Dictionaries/
```

然后打开 Dictionary.app，在设置里启用 `DeepDict`。

V2 还没有打包发布，目前需要按下面的"构建"一节从源码生成。

## 词库来源

候选词表由以下来源合并去重得到，详见 [docs/wordlists.md](docs/wordlists.md)：

- **词频表**：从 wordfreq 取约 10 万个高频英语词并清理。
- **社区语料**：LessWrong、Hacker News、Reddit 评论，补充论坛和技术社区里的常见表达。
- **核心词表**：Oxford 5000，保证基础阅读词汇的覆盖。
- **学术词表**（V2 新增）：认知科学及相关学科（神经科学、心理学、AI、哲学、语言学、统计）的术语，来自 Wikipedia 术语表、Wiktionary 学科分类、arXiv 摘要和斯坦福哲学百科。

模型在生成时判断每个词是否收录。明显的拼写错误、碎片、缩写、无法可靠识别的词会被排除，但排除记录会保留，便于审计。

## 质量

词条是 LLM 生成的，不应当作权威词典数据使用。已经做过的质量工作：

- **规则扫描**（不消耗 token）：检测"把生词看成形近的常见词"这类误读，并与 ECDICT 交叉核对，给每个词条分风险层。
- **双模型审查**：风险最高的 647 条先由 DeepSeek 审查，被判有问题的 274 条再由 GPT 复审。
- **人工修正**：两个模型一致判为有问题的 66 条已逐条复核，修正 12 条，排除 7 条，记录在 `data/corrections/`。

还没做的：人工金标样本评估（样本已抽好，未标注），以及中低风险层的审查。详见 [docs/pipeline.md](docs/pipeline.md)。

## 构建

需要 Python 3.9 以上、`zstd`，以及 Apple 的 Dictionary Development Kit（在 Xcode 的 Additional Tools 里）。

```sh
python3 -m venv .venv
```

```sh
.venv/bin/pip install -e .
```

解出词条：

```sh
mkdir -p work && zstd -dc data/entries/deepdict-v2-entries.tar.zst | tar -xf - -C work
```

生成词典源文件：

```sh
.venv/bin/python -m deepdict.cli.build_apple --entries-dir work/entries --output-dir build/deep-dict-v2 --dict-name "DeepDict V2" --package-name DeepDictV2 --display-name "DeepDict V2" --bundle-id org.deepdict.dictionary.v2 --clean
```

编译并安装：

```sh
make -C build/deep-dict-v2 DICT_BUILD_TOOL_DIR="/path/to/Dictionary Development Kit" all install
```

重新生成词条、运行 QA 的方法见 [docs/pipeline.md](docs/pipeline.md)。

## 仓库结构

- `deepdict/`：全部代码。`wordlists/` 构建候选词表，`cli/` 是生成、清洗、QA、验证、构建各步骤的入口，`prompts/` 是提示词。
- `data/generation-targets/`：各来源的候选词表。
- `data/entries/deepdict-v2-entries.tar.zst`：V2 全部词条（含被排除的记录）。
- `data/final-wordlists/included-words.csv`：V2 最终收录的词。
- `data/corrections/`：人工修正记录。
- `release/`：V1 的发布产物。
- `docs/`：流水线和词表来源的说明。

## 开源说明

正式发布前，还需要明确代码、生成数据和发布产物各自的许可证，并核对第三方词表来源的再分发限制。
