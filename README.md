# DeepDict

DeepDict 是一部给中文母语者读英文用的英汉词典。它的目标只有一个：读到不认识的词时，尽快在上下文里看懂，然后回去继续读。

当前版本（V2）收录 96,669 个词，共 136,222 个义项，词条由 LLM 生成。成品是 macOS 词典包，用于 Dictionary.app 和系统的"查询"弹窗。

<img src="assets/sample-token.png" alt="DeepDict Lookup 示例：token" width="520">

## 仓库里有什么

这个仓库有两块核心内容，其余都是围绕它们的工具。

| 目录 | 内容 |
| --- | --- |
| [`wordlists/`](wordlists/) | **收哪些词。** 各来源的候选词表，以及提取它们的脚本 |
| [`dictionary/`](dictionary/) | **词典结果。** 全部词条、收录词表、可安装的词典包 |
| [`deepdict/`](deepdict/) | 把词表变成词典的工具：生成、质量检查、构建 |

## 安装

解压 `dictionary/DeepDict.dictionary.zip`，把 `DeepDict.dictionary` 复制到：

```sh
~/Library/Dictionaries/
```

然后打开 Dictionary.app，在设置里勾选 `DeepDict`。

## 它是什么样的词典

DeepDict 是阅读辅助词典，不是学习词典，也不是百科全书。

- **释义以解释为主。** 只给一串近义翻译（如 serious＝严重的；严肃的；认真的）等于把辨义留给读者。97% 的义项带一句话解释，说明这个词在这个意思下到底指什么。
- **义项按真实阅读频率排序和裁剪。** 平均每个词 1.4 个义项，罕见义项通常不收。
- **不收例句、音标、词源、搭配和用法说明。** 这些对"读懂当前这句"没有帮助，只会让弹窗变长。
- **不系统收录专有名词。** 人物、机构、品牌、产品、事件更适合查百科。

词条是 LLM 生成的，不应当作权威词典数据使用。做过哪些质量检查、还有哪些没做，见 [dictionary/README.md](dictionary/README.md)。

## 开源说明

正式发布前，还需要明确代码、生成数据和词典包各自的许可证，并核对第三方词表来源的再分发限制。
