# 工具

这个包把 `wordlists/` 里的候选词变成 `dictionary/` 里的词典。

## 环境

```sh
python3 -m venv .venv
```

```sh
.venv/bin/pip install -e .
```

还需要一样放在本地、不进 git 的资源：

| 资源 | 默认位置 | 用途 |
| --- | --- | --- |
| ECDICT | `work/vendor/ecdict/ecdict.csv` | 质量扫描时做交叉核对 |

只有编译 macOS 词典包时才需要 Apple 的 Dictionary Development Kit（在 Xcode 的 Additional Tools 里），默认放在 `work/vendor/ddk/`。

## 本地工作区

所有中间产物都在 `work/` 下，这个目录不进 git。

| 位置 | 内容 |
| --- | --- |
| `work/entries/` | 解开的词条，各步骤都在这里读写 |
| `work/qa/` | 质量扫描和双模型投票的结果 |
| `work/verify/` | 模型审查的逐词判决 |
| `work/runs/` | 各次运行的日志和汇总 |
| `work/build/` | macOS 词典的构建目录 |
| `work/build-formats/` | MDict 和 StarDict 的中间文件 |

第一次使用时先解出词条：

```sh
.venv/bin/python -m deepdict.cli.archive unpack
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

### 5. 准确性抽查

分层抽样：

```sh
.venv/bin/python -m deepdict.cli.accuracy sample --size 800
```

样本写在 `work/accuracy/sample.csv`。接下来为每个词取参照词典的释义，按 `prompts/accuracy-judge.md` 的标准逐条判定，判定结果放进 `work/accuracy/verdicts/`。取参照释义的脚本和参照原文都不在仓库里。

汇总成逐词结果：

```sh
.venv/bin/python -m deepdict.cli.accuracy collect
```

输出加权后的估计和置信区间：

```sh
.venv/bin/python -m deepdict.cli.accuracy report
```

`report` 只读 `dictionary/accuracy.csv`，所以拿到仓库就能重算这些数字。

### 6. 打包

词条有改动后，按下面的顺序更新 `dictionary/` 里的文件。

更新词条归档和收录词表：

```sh
.venv/bin/python -m deepdict.cli.archive pack
```

生成 MDict 和 StarDict 两个包。命令会把生成的文件读回来，逐条和源数据核对：

```sh
.venv/bin/python -m deepdict.cli.build_formats
```

生成 macOS 词典的源文件：

```sh
.venv/bin/python -m deepdict.cli.build_apple --clean
```

编译 macOS 词典，结果是 `work/build/objects/DeepDict.dictionary`。把末尾的 `all` 换成 `all install` 可以直接装到本机：

```sh
make -C work/build DICT_BUILD_TOOL_DIR="$PWD/work/vendor/ddk" all
```

打成 zip：

```sh
ditto -c -k --keepParent work/build/objects/DeepDict.dictionary dictionary/DeepDict.dictionary.zip
```

三种词典包共用同一份词条。macOS 版的排版在 `build/render.py`，MDict 和 StarDict 共用 `build/html.py`，后者把样式写在词条内，颜色在深色和浅色界面下都能看清。

## 决定不做的

- **词根词缀拆分**。做过设计和小样后取消了，它对读懂当前句子帮助不大。
- **音标**。将来要做的话应直接用 ECDICT 的 `phonetic` 列，不要让模型生成。
