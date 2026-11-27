# 词典结果

这个目录是 DeepDict V2 的成品。

| 文件 | 内容 |
| --- | --- |
| `DeepDict.dictionary.zip` | 可直接安装的 macOS 词典包 |
| `entries.tar.zst` | 全部 106,879 条词条记录，一词一个 JSON，包括被排除的词 |
| `included-words.csv` | 最终收录的 96,669 个词 |
| `corrections.jsonl` | 人工修正过的 19 条词条 |

## 安装

解压 `DeepDict.dictionary.zip`，把 `DeepDict.dictionary` 复制到 `~/Library/Dictionaries/`，然后在 Dictionary.app 的设置里勾选 `DeepDict`。

## 数字

| 项目 | 数量 |
| --- | --- |
| 候选词 | 106,879 |
| 收录 | 96,669 |
| 排除 | 10,210 |
| 义项 | 136,222，平均每词 1.41 个 |
| 带解释的义项 | 131,859，占 97% |

排除的原因主要是模型无法可靠识别这个词（9,016 个），其次是拼写错误或碎片（609 个）、缩写（199 个）、不是英语词（170 个）。

## 词条格式

解开 `entries.tar.zst` 得到 `entries/` 目录，每个文件是一条记录：

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

| 字段 | 含义 |
| --- | --- |
| `include` | 是否收录。为 `false` 时 `senses` 为空，`exclude_reason` 说明原因 |
| `senses` | 义项，按阅读中遇到的频率排序 |
| `pos` | 词性，如 `n.`、`v.`、`adj.` |
| `context_label` | 语境或领域标签，可为空 |
| `gloss_zh` | 简短的中文对应词 |
| `definition_zh` | 一句话解释，可以没有 |
| `suitability_score`、`meaning_confidence` | 模型自评的 0–10 分，只用于质量检查时排序 |

格式的权威定义是 `deepdict/schema.py` 里的 `validate_entry()`。

## 词条是怎么来的

- V1（2026 年 4 月）用 DeepSeek 生成了 `wordlists/merged.csv` 的 100,683 个词，收录 91,813 个。
- V2（2026 年 6 月）把这 91,813 个词用新的提示词全部重新生成，走的是 Codex 订阅。新提示词把"解释"从可选项变成了主体。V1 里被排除的 8,870 个词沿用 V1 的记录。
- V2 另外生成了 `wordlists/cogsci/words.csv` 的 6,196 个学术词，收录 5,606 个。

## 质量

词条是 LLM 生成的，不应当作权威词典数据使用。

**做过的检查**

1. **规则扫描**，不消耗 token。检测"把生词看成形近的常见词"这类误读，并与 ECDICT 交叉核对，按风险把词条分成 A、B、C 三层。
2. **双模型审查**，只做了风险最高的 A 层。当时 A 层有 647 条，DeepSeek 判 274 条有问题，GPT 复审后两者一致的有 66 条。
3. **人工修正**。这 66 条逐条复核：12 条改了释义，7 条改为排除，47 条保留。改过的 19 条记录在 `corrections.jsonl`。

**没做的**

- 208 条两个模型意见不一致的词条没有复核。抽看的结果是多数没问题。
- B 层（约 1.9 万条）和 C 层（约 2.3 万条）没有做模型审查。
- 没有人工评估过的准确率。已经从 V2 分层抽了 477 个词，等人工标注后才能算出真实错误率。
