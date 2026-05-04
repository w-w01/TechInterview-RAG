# RAG 设计说明

## 本地种子如何加载

- 文件路径：`backend/data/interview_qa_seed.json`。
- `data_loader.load_interview_seed()` 在进程启动时读取为 Python 字典列表。
- 每条包含：`id`、`topic`、`difficulty`、`question`、`answer`、`key_points`、`tags`、`source`。

## 检索如何工作

1. **向量化文本**：对每条记录拼接 `Topic`、`Difficulty`、`Question`、`Reference answer`、`Key points` 形成一段文档文本（见 `rag._doc_text`）。
2. **Embedding**：使用 OpenAI `text-embedding-3-small` 批量嵌入；向量 **L2 归一化** 后写入 **FAISS** `IndexFlatIP`（内积等价于余弦相似度）。
3. **查询**：将用户查询文本（出题时为当前题干；评卷时为「题干 + 考生答案」）嵌入后检索 top-N，再 **优先保留同 `topic`** 的条目，不足时用其他主题补齐。

## 答案评估如何工作

1. 用上述检索得到若干条参考 QA，拼成 `reference_block`，并把检索条目的 `key_points` 合并为 `key_points_block`。
2. 使用 `prompts.EVALUATION_SYSTEM_PROMPT` 定义 rubric 与输出 JSON 字段约束。
3. 调用 `gpt-4o-mini`，`response_format=json_object`，服务端解析并校验 `score` 在 0–10。

## 引用 / 证据如何产生

- **出题接口**：当前选中题作为首条引用，其余为向量近邻条目，格式化为 `source + Q/A 摘要`。
- **评卷接口**：`reference_evidence` 为检索到的条目同样格式化后的列表，供前端展示「引用证据」。

## 后续可改进方向

- 混合检索（BM25 + 向量）与 rerank。
- 题目生成由「纯抽取」改为「在检索片段约束下的生成」并做安全过滤。
- 评估指标与人工标注对齐、缓存 Embedding 以节省成本。
