# 工具

这个包把 `wordlists/` 里的候选词变成 `dictionary/` 里的词典。

## 环境

```sh
python3 -m venv .venv
```

```sh
.venv/bin/pip install -e .
```

还需要 `zstd` 命令，以及两样放在本地、不进 git 的资源：

| 资源 | 默认位置 | 用途 |
| --- | --- | --- |
| ECDICT | `work/vendor/ecdict/ecdict.csv` | 质量扫描时做交叉核对 |
| Apple Dictionary Development Kit | `work/vendor/ddk/` | 编译 macOS 词典。在 Xcode 的 Additional Tools 里 |

## 本地工作区

所有中间产物都在 `work/` 下，这个目录不进 git。

| 位置 | 内容 |
| --- | --- |
| `work/entries/` | 解开的词条，各步骤都在这里读写 |
| `work/qa/` | 质量扫描和双模型投票的结果 |
| `work/verify/` | 模型审查的逐词判决 |
| `work/runs/` | 各次运行的日志和汇总 |
| `work/build/` | 词典构建目录 |

第一次使用时先解出词条：

```sh
mkdir -p work && zstd -dc dictionary/entries.tar.zst | tar -xf - -C work
```

## 步骤

### 1. 生成词条

```sh
.venv/bin/python -m deepdict.cli.generate_entries_batch --words wordlists/merged.csv
```

- 一次调用生成一批词，默认 50 个，多批并发。
- 已有输出文件的词会跳过，中断后重跑同一条命令就是续跑。
- `--backend codex` 走 Codex 订阅，`--backend api` 走兼容 OpenAI 的 HTTP 接口（默认 DeepSeek，需要 `DEEPSEEK_API_KEY`）。
- 连续 3 批失败会自动停止，通常是额度用完了。
- 失败的词放在 `work/entries-failures/`，不阻塞其他词。

提示词是 `prompts/entry-generation-system.md`。

### 2. 质量扫描

```sh
.venv/bin/python -m deepdict.cli.qa_scan
```

不消耗 token，约 20 秒。对每个收录的词条计算四种信号：

| 信号 | 含义 |
| --- | --- |
| 误读 | 释义和形近词的 ECDICT 释义吻合，和本词的不吻合 |
| 形近词未决 | 有一个高频形近词，且本词释义没有被 ECDICT 佐证 |
| 零重叠 | ECDICT 收了这个词，但释义完全对不上 |
| 无证据 | 罕见词，ECDICT 也没收 |

A 层是有两个以上强信号的，B 层有一个，C 层只是模型自评分低。结果写在 `work/qa/`，`risk-ranked.csv` 是下一步的输入，`report.md` 是汇总。

信号只用来排序，不是判决。A 层里也有很多没问题的词。

### 3. 模型审查

第一个模型审查指定的风险层：

```sh
.venv/bin/python -m deepdict.cli.verify_entries --tiers A
```

第二个模型复审被判有问题的词：

```sh
.venv/bin/python -m deepdict.cli.verify_vote
```

两个模型都判有问题的才算高置信，只有一个判的留给人工复核。用两个不同的模型，是因为它们犯的错相互独立。

### 4. 人工修正

逐条复核高置信的问题词条，直接改 `work/entries/` 里的 JSON，并把改后的词条追加到 `dictionary/corrections.jsonl`。

### 5. 抽样评估（还没做）

```sh
.venv/bin/python -m deepdict.cli.gold_sample
```

按风险层和词频分层抽样，输出 `work/qa/gold-sample.csv`。人工在 `label` 列填 ok、wrong_word、fabricated、wrong_senses 或 partly_wrong，之后可以算出词典的错误率。

### 6. 构建词典

```sh
.venv/bin/python -m deepdict.cli.build_apple --clean
```

```sh
make -C work/build DICT_BUILD_TOOL_DIR="$PWD/work/vendor/ddk" all
```

编译结果是 `work/build/objects/DeepDict.dictionary`。在后一条命令末尾把 `all` 换成 `all install` 可以直接装到本机。

### 7. 更新成品

词条有改动后，更新 `dictionary/` 里的三个文件。

词条压缩包：

```sh
(cd work && find entries -name '*.json' | LC_ALL=C sort | COPYFILE_DISABLE=1 tar -cf - --no-xattrs -T - | zstd -19 -T0 -q -f -o ../dictionary/entries.tar.zst)
```

词典安装包：

```sh
ditto -c -k --keepParent work/build/objects/DeepDict.dictionary dictionary/DeepDict.dictionary.zip
```

收录词表 `included-words.csv` 是所有 `include` 为 `true` 的词，按字母排序。

## 决定不做的

- **词根词缀拆分**。做过设计和小样后取消了，它对读懂当前句子帮助不大。
- **音标**。将来要做的话应直接用 ECDICT 的 `phonetic` 列，不要让模型生成。
