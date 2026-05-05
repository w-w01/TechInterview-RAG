# RAG 设计说明

## 本地种子如何加载

- 文件路径：`backend/data/interview_qa_seed.json`。
- `data_loader.load_interview_seed()` 在进程启动时读取为 Python 字典列表。
- 每条包含：`id`、`topic`、`difficulty`、`question`、`answer`、`key_points`、`tags`、`source`。

## 检索如何工作

1. **向量化文本**：对每条记录拼接 `Topic`、`Difficulty`、`Question`、`Reference answer`、`Key points` 形成一段文档文本（见 `rag._doc_text`）。
2. **Embedding**：使用 OpenAI `text-embedding-3-small` 批量嵌入；向量 **L2 归一化** 后写入 **FAISS** `IndexFlatIP`（内积等价于余弦相似度）。
3. **查询**：评卷时将「题干 + 考生答案」嵌入后检索 top-N，再 **优先保留同 `topic`** 的条目，不足时用其他主题补齐。（出题接口不使用检索。）

## 答案评估如何工作

1. 请求必须携带 **`question_id`**：服务端用其在种子中定位**当前题**（canonical），并校验与 `topic`、`difficulty`、`question` 文本一致。
2. 向量检索仍以「题干 + 考生答案」为查询，取近邻条目；与 canonical **按 id 去重合并**，最多 5 条，**canonical 始终排在首位**，拼成 `reference_block` 与合并后的 `key_points_block`。
3. 使用 `prompts.EVALUATION_SYSTEM_PROMPT` 定义 rubric 与输出 JSON 字段约束。
4. 调用 `gpt-4o-mini`，`response_format=json_object`，服务端解析并校验 `score` 在 0–10。

## 引用 / 证据如何产生

- **出题接口**：`reference_snippets` 固定为空列表；题目来自种子过滤后的随机抽取。
- **评卷接口**：`reference_evidence` 与 prompt 共用上述合并列表（**首条为当前题**，其余为近邻），供前端展示「引用证据」。

## 后续可改进方向

- 混合检索（BM25 + 向量）与 rerank。
- 题目生成由「纯抽取」改为「在检索片段约束下的生成」并做安全过滤。
- 评估指标与人工标注对齐、缓存 Embedding 以节省成本。
