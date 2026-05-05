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

### B. JD 文本 RAG 组卷（规划中，尚未编码）

**目标**：用户粘贴 **JD 纯文本**，仅用向量检索 ** assembly 试卷**，不改变评卷链路。

1. **索引构建（启动时，实现后）**：对每条种子将「Topics / Difficulty / Question / Reference answer / Key points」拼成文档文本，批量调用 OpenAI **`text-embedding-3-small`**，向量 **L2 归一化** 后常驻内存（题库规模约 200，可用 numpy 矩阵批量余弦相似度，无需强制 FAISS）。
2. **组卷请求**：`POST /generate-paper-from-jd`，body 含 `jd_text`、`difficulty`、`count`（含默认与上限，以实现为准）。
3. **检索**：将 JD 文本（过长则截断）嵌入为查询向量；仅在 **`difficulty` 与请求一致** 的种子子集中计算相似度，按得分取 Top‑`count`，**按 `id` 去重**；若子集不足 `count` 则返回该子集按相似度排序的全部剩余题目。
4. **响应**：返回与单次 **`/generate-question`** 同结构的题目列表，供前端选题并调用现有 **`/evaluate-answer`**。
5. **不做**：用 LLM 先从 JD 抽取结构化技能再检索（可列为后续）；JD PDF 上传；评卷阶段合并向量邻居或注入 JD 全文。

## 评卷如何工作（仅本题，已实现）

1. 请求必须携带 **`question_id`**，且 **`topics`** 与题目自身 `topics` 标签 **有交集**；并校验 `difficulty`、`question` 文本与种子一致。
2. **不向量化、不检索**：将 **canonical 本题一条** 的题干与参考答案拼成 `reference_block`，将本题 **`key_points`** 拼成 `key_points_block`（无其它条目合并）。**JD 组卷交付的题目仍走同一评卷逻辑**。
3. 使用 `prompts.EVALUATION_SYSTEM_PROMPT` 定义 rubric 与输出 JSON 字段约束。
4. 调用 `gpt-4o-mini`，`response_format=json_object`，服务端解析并校验 `score` 在 0–10。

## 引用 / 证据如何产生

- **`/generate-question`**：`reference_snippets` 固定为空列表。
- **`/evaluate-answer`**：`reference_evidence` 仅为 **本题** 对应的引用片段列表（长度 1），与 prompt 同源。

## 健康检查字段说明（现状与规划）

- **`rag_index_ready`**（已实现）：题库已成功加载且条目非空。
- **`embedding_index_ready`**（**规划**，代码落地后）：JD 组卷用 embedding 矩阵 / 索引是否已成功构建；与 `rag_index_ready` 分列，避免「有无向量索引」语义混淆。

## 后续可改进方向

- JD 经 LLM 压缩为查询向量或与关键词检索混合。
- 题目在检索约束下的生成并做安全过滤。
- 评估指标与人工标注对齐。
