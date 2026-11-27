# DeepDict 流水线

这份文档说明词典是怎么从词表一步步做出来的，每一步用哪个命令，以及数据放在哪里。

## 环境

```sh
python3 -m venv .venv
```

```sh
.venv/bin/pip install -e .
```

核心流程只依赖 `wordfreq`。重建 Hacker News 和 Reddit 词表还需要 `datasets` 等包，用 `.venv/bin/pip install -e ".[wordlists]"` 安装。

另外需要的本地资源（都不进 git）：

| 资源 | 位置 | 用途 |
| --- | --- | --- |
| ECDICT | `vendor/ecdict/ecdict.csv` | QA 扫描时做交叉核对 |
| Dictionary Development Kit | `build/ddk-local/` 或 Xcode Additional Tools | 编译 macOS 词典 |
| `zstd` | 系统命令 | 读写词条压缩包 |

## 目录

| 位置 | 是否进 git | 内容 |
| --- | --- | --- |
| `data/generation-targets/` | 是 | 各来源的候选词表 |
| `data/entries/deepdict-v2-entries.tar.zst` | 是 | V2 全部词条，106,879 条 |
| `data/final-wordlists/included-words.csv` | 是 | V2 收录的 96,669 个词 |
| `data/corrections/` | 是 | 人工修正过的词条记录 |
| `work/entries/` | 否 | 解开的词条，一词一个 JSON，各步骤的工作目录 |
| `work/qa/` | 否 | QA 扫描和双模型投票的结果 |
| `work/verify/` | 否 | 验证步骤的逐词判决 |
| `work/runs/` | 否 | 各次运行的日志和汇总 |
| `build/` | 否 | 词典构建目录 |

第一次使用时先解出词条：

```sh
mkdir -p work && zstd -dc data/entries/deepdict-v2-entries.tar.zst | tar -xf - -C work
```

## 词条格式

每个词一个 JSON 文件，文件名是 `w_<id>.json`，id 由 `deepdict/ids.py` 从词头算出。格式由 `deepdict/schema.py` 的 `validate_entry()` 定义：

```json
{
  "word": "a",
  "include": true,
  "suitability_score": 10,
  "meaning_confidence": 10,
  "exclude_reason": null,
  "senses": [
    {"pos": "det.", "context_label": "", "gloss_zh": "某个", "definition_zh": "用来指一个未具体说明的人或事物。"}
  ]
}
```

- `include` 为 `false` 的词不进词典，但记录保留，`exclude_reason` 说明原因。
- `gloss_zh` 是简短的中文对应词，`definition_zh` 是一句话解释，可以没有。
- `suitability_score` 和 `meaning_confidence` 是模型自评的 0–10 分，只用于 QA 排序。

## 步骤

### 1. 构建候选词表

见 [wordlists.md](wordlists.md)。结果是 `data/generation-targets/` 下的若干 `words.csv`。

### 2. 生成词条

```sh
.venv/bin/python -m deepdict.cli.generate_entries_batch --words data/generation-targets/merged-clean/words.csv --out-dir work/entries
```

- 一次调用生成一批词（默认 50 个），多批并发。
- 已有输出文件的词会跳过，所以中断后重跑同一条命令就是续跑。
- `--backend codex` 走 Codex 订阅（V2 用的方式），`--backend api` 走兼容 OpenAI 的 HTTP 接口（默认 DeepSeek，需要 `DEEPSEEK_API_KEY`）。
- 连续 3 批失败会自动停止，通常是额度用完了。
- 失败的词放在 `<out-dir>-failures/`，不阻塞其他词。

提示词是 `deepdict/prompts/entry-generation-system.md`。V1 的提示词保留为 `entry-generation-system-v1.md`，仅供对照。

### 3. 清洗（可选）

```sh
.venv/bin/python -m deepdict.cli.clean_entries --input-dir work/entries --dedupe exact
```

不调用模型，只做去重和括号迁移这类机械清理。V1 用过，V2 没有用。

### 4. QA 扫描

```sh
.venv/bin/python -m deepdict.cli.qa_scan
```

不消耗 token，约 20 秒跑完。对每个收录的词条计算四种信号：

| 信号 | 含义 |
| --- | --- |
| 误读 | 释义和形近词的 ECDICT 释义吻合，和本词的不吻合 |
| 形近词未决 | 有一个高频形近词，且本词释义没有被 ECDICT 佐证 |
| 零重叠 | ECDICT 收了这个词，但释义完全对不上 |
| 无证据 | 罕见词，ECDICT 也没收 |

然后分层：A 层是有两个以上强信号的，B 层有一个，C 层只是模型自评分低。结果写在 `work/qa/`，其中 `risk-ranked.csv` 是下一步的输入，`report.md` 是汇总。

信号只用来排序，不是判决。A 层里也有很多没问题的词。

### 5. 模型验证

第一个模型审查指定风险层：

```sh
.venv/bin/python -m deepdict.cli.verify_entries --tiers A
```

第二个模型复审被判有问题的词：

```sh
.venv/bin/python -m deepdict.cli.verify_vote
```

两个模型都判有问题的才算高置信，只有一个判的留给人工复核。用两个不同的模型是因为它们犯的错相互独立。

### 6. 人工修正

对高置信的问题词条逐条复核，直接改 `work/entries/` 里的 JSON，并把改后的词条追加到 `data/corrections/` 下的记录文件里。

### 7. 构建词典

```sh
.venv/bin/python -m deepdict.cli.build_apple --entries-dir work/entries --output-dir build/deep-dict-v2 --dict-name "DeepDict V2" --package-name DeepDictV2 --display-name "DeepDict V2" --bundle-id org.deepdict.dictionary.v2 --clean
```

```sh
make -C build/deep-dict-v2 DICT_BUILD_TOOL_DIR="$PWD/build/ddk-local" all install
```

### 8. 归档

词条有改动后，重新打包并更新收录词表：

```sh
(cd work && find entries -name '*.json' | LC_ALL=C sort | COPYFILE_DISABLE=1 tar -cf - --no-xattrs -T - | zstd -19 -T0 -q -f -o ../data/entries/deepdict-v2-entries.tar.zst)
```

## V2 做到了哪一步

| 步骤 | 状态 |
| --- | --- |
| 生成 | 完成。V1 收录的 91,813 词用 V2 提示词全部重新生成（Codex 订阅，2026-06），另加 6,196 个学术词 |
| QA 扫描 | 完成。A 层 637，B 层 18,641，C 层 22,785，无信号 54,606 |
| 模型验证 | 只做了 A 层。当时的 647 条中，DeepSeek 判 274 条有问题，GPT 复审后 66 条两者一致 |
| 人工修正 | 66 条一致判定的已全部复核：修正 12 条，排除 7 条，其余 47 条保留 |

## 没做的事

- **208 条分歧词条没有复核。** 抽看的结果是 GPT 多数判断正确（词条没问题），所以优先级低。清单在 `work/qa/review-contested.csv`。
- **B 层和 C 层没有做模型验证。**
- **没有人工评估的准确率。** `work/qa/gold-sample.csv` 是从 V2 分层抽的 477 个词，`label` 列待填（建议值：ok / wrong_word / fabricated / wrong_senses / partly_wrong）。标注完才能算出词典的真实错误率。
- **词根词缀拆分**做过设计和小样，后来取消了，代码已删除。它对读懂当前句子帮助不大。
- **音标**决定不做。将来要做的话应直接用 ECDICT 的 `phonetic` 列，不要让模型生成。
