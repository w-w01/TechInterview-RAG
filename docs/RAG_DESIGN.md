# 题库与评卷设计说明

（文件名沿用 `RAG_DESIGN.md`。）

## 本地种子如何加载

- 文件路径：`backend/data/interview_qa_seed.json`。
- **Topic 白名单**：`backend/data/topic_allowlist.json`（`slug` + `label`），启动时与种子一并校验。
- `data_loader.load_interview_seed()` 在进程启动时读取为 Python 字典列表。
- 每条包含：`id`、`topics`（字符串数组）、`difficulty`、`question`、`answer`、`key_points`、`tags`（可选）、`source`（可选）。详见 [DATA_SCHEMA.md](DATA_SCHEMA.md)。

## 出题如何工作

### A. Topic 随机池（已实现）

1. 请求中的 **`topics`** 经白名单校验、去重。
2. 候选池：种子中 **`topics` 与用户所选 slug 至少有一个交集（OR）**，且 **`difficulty`** 与请求一致。
3. 在候选池中 **`random.choice` 抽一题**，返回 `question_id`、题干、`expected_key_points` 等。
4. **不使用** Embedding 或向量检索。

### B. AI 条件出题（已实现，非向量）

1. 与随机真题 **相同的过滤池**（topic OR + 难度）。
2. 从池中 **无放回随机抽样** 至多 `reference_max` 条（为 0 则不抽样）；池空则 **零样本**。
3. 将标签、难度与样条拼入 prompt，LLM 输出 JSON：`question`、`expected_key_points`。
4. 服务端登记 **`generation_id` 快照**（题干、要点、抽样 `source_seed_ids`）；评卷时 **仅认快照题干**，参考块由这些种子重载。

### C. JD 文本 RAG 组卷（已实现）

1. **索引构建（启动时）**：对每条种子将「Topics / Difficulty / Question / Reference answer / Key points」拼成文档文本（见 `embedding_index.doc_text_for_embedding`），批量调用 OpenAI **`text-embedding-3-small`**，向量 **L2 归一化** 后存入 **`numpy`** 矩阵（行与 `_seed_items` 下标对齐）。
2. **组卷请求**：`POST /generate-paper-from-jd`，body 含 `jd_text`（最短约 40 字）、`difficulty`、`count`（1–20）。
3. **检索**：JD 文本截断后嵌入；仅在 **同难度** 子集上与种子向量做 **内积（等价余弦）** 排序，取 Top‑`count`，**按 `id` 去重**。
4. **混卷与解释**：响应返回 `questions`（真题 + AI 题）与 `meta`（AI 占比、是否提升、候选重复占比、补弱关键词等）。
5. **试卷实体化**：若提供 `session_id`，后端会创建 `paper_id` 并将每道题以 `attempt` 形式归档到该试卷，便于后续做整卷统计与自适应策略。
6. **去重策略**：同一会话内默认排除“已评估”题目（`score != null`）避免重复；AI 题按题干规范化去重（可容忍改写题语义重复用于巩固练习）。
7. **评卷入口**：真题走 **`question_id`**，AI 题走 **`generation_id`**，均复用同一 rubric。
8. **不做（仍）**：评卷阶段合并向量邻居或注入 JD 全文；JD PDF 上传（可后续）。

## 评卷如何工作（已实现）

### 真题（`question_id`）

1. **`topics`** 与题目自身标签 **有交集**；校验 `difficulty`、`question` 与种子一致。
2. **canonical 单条**：`reference_block` 与 `key_points_block` 仅来自本题种子。

### AI 题（`generation_id`）

1. 校验快照存在且 **`question` / `difficulty` 与快照一致**；`topics` 与快照标签有交集。
2. `key_points_block` 来自出题时 LLM 给出的要点；`reference_block` 由 **`source_seed_ids`** 对应种子重拼（零样本时可为空说明）。

真题与 AI 题均使用 `prompts.EVALUATION_SYSTEM_PROMPT` 与 `gpt-4o-mini` 的 JSON 评卷解析，**0–10** 分。

## 引用 / 证据如何产生

- **`/generate-question`**：`reference_snippets` 固定为空列表。
- **`/generate-question-llm`**：`reference_snippets` 为本次少样本抽样的种子片段。
- **`/evaluate-answer`**：真题 `reference_evidence` 为 **单条** canonical；AI 题为 **多条** 抽样种子片段（零样本时可为空列表）。

## 健康检查字段说明

- **`rag_index_ready`**：题库已成功加载且条目非空。
- **`embedding_index_ready`**：启动时种子 **Embedding 矩阵** 是否已成功构建（失败则 JD 组卷接口返回 503）。

## 后续可改进方向

- JD 经 LLM 压缩为查询向量或与关键词检索混合。
- 题目在检索约束下的生成并做安全过滤。
- 评估指标与人工标注对齐。
- “已答过”集合当前按 `score != null` 定义，可扩展为“已展开/已作答未评估”亦计入，避免用户中断后重复。
