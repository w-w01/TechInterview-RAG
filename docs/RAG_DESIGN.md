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

### C. JD 文本 RAG 组卷（已实现：Planner + Selector）

1. **索引构建（启动时）**：对每条种子将「Topics / Difficulty / Question / Reference answer / Key points」拼成文档文本（见 `embedding_index.doc_text_for_embedding`），批量调用 OpenAI **`text-embedding-3-small`**，向量 **L2 归一化** 后存入 **`numpy`** 矩阵（行与 `_seed_items` 下标对齐）。
2. **组卷请求**：`POST /generate-paper-from-jd`，body 含 `jd_text`（最短约 40 字）、`difficulty`、`count`（1–20）、`auto_adapt`、`session_id`（可选）。
3. **向量检索（候选池）**：JD 截断后嵌入；在难度子集上（`auto_adapt=true` 时为 beginner/intermediate/advanced 三路）做 **余弦 Top‑K**，合并 **按 `id` 去重** 得到与 JD 相关的有序候选列表。
4. **Planner（LLM）**：读取 JD 与 **topic 白名单**（`topic_allowlist.json`），只输出 JSON：`topic_priority`（合法 slug 数组，高→低）与 `notes`。若模型未给出合法 slug，则 **程序回退** 为「候选频次 + 会话弱点加权」排序（与旧规则一致，保证可组卷）。
5. **候选送给 Selector**：按 Planner 的 topic 顺序从检索结果中 **分层抽样**（每 topic 条数上限、总条数上限见环境变量 `JD_CANDIDATE_PER_TOPIC`、`JD_SELECTOR_MAX_ITEMS`），每条含 `question_id`、题干、`topics`、难度、`key_points_preview`（缩短要点，省 token）。
6. **Selector（LLM）**：在提示中注入 JD 摘要、topic 优先级、**真题道数 / AI 道数**、单 topic 真题上限、会话薄弱词、最近卷 **topic 推荐难度**（`topic_level_plan`），以及候选 JSON。**输出**仅允许使用候选中的 `question_id`；并输出 `ai_slots`（每道含 `topics` + `difficulty`），供后续 AI 出题。
7. **程序校验**：剔除非法 id、去重、按单 topic 上限过滤与 **不足补齐**；若 Selector 首次 JSON 未满足「真题 id 全在候选内、无重复、条数严格等于要求、ai_slots 长度严格等于要求」，则 **附带校验错误说明与合法 id 节选再调用 Selector 一次**；仍不足则由程序在 `program_fixes` 中记录并补齐。规范 `ai_slots` 条数后，对每槽按标签与难度从池中 **少样本抽样** 调用既有 AI 出题逻辑，生成 `generation_id` 题。
8. **混卷与解释**：响应 `questions`（真题 + AI 题交错）与 `meta`（含 `planner_notes`、`selector_notes`、`selector_candidate_count`、`program_fixes`、原 AI 占比与自适应字段等）。
9. **试卷实体化**：若提供 `session_id`，创建 `paper_id` 并写入 `attempts`。
10. **去重**：同会话已评估（`score != null`）的真题与题干 key 不参与新卷；AI 题重复题干会重试或真题补位。
11. **评卷**：真题 `question_id`，AI 题 `generation_id`，rubric 不变。
12. **仍不做**：评卷阶段向量扩召回；JD PDF 上传。

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

## `GET /sessions/{id}/next-paper-plan` 与 topic_priority 来源

- 响应中 **`topic_priority`**：优先取自**本会话最近一张试卷**的 `meta.topic_priority`（JD 组卷卷 `source=jd_rag_mix` 时，与当次 Planner/程序回退一致）；若无则用题库前 120 条 + 弱点计数的 **stub 排序**。
- **`topic_priority_source`**：`last_paper_meta` 或 `seed_frequency_weakness_stub`；**`topic_priority_explanation`** 为中文说明。本条接口**不调用** JD Planner LLM，调试时勿与 `POST /generate-paper-from-jd` 的实时 Planner 混为一谈。

## 健康检查字段说明

- **`rag_index_ready`**：题库已成功加载且条目非空。
- **`embedding_index_ready`**：启动时种子 **Embedding 矩阵** 是否已成功构建（失败则 JD 组卷接口返回 503）。

## 后续可改进方向

- JD 经 LLM 压缩为查询向量或与关键词检索混合。
- 题目在检索约束下的生成并做安全过滤。
- 评估指标与人工标注对齐。
- “已答过”集合当前按 `score != null` 定义，可扩展为“已展开/已作答未评估”亦计入，避免用户中断后重复。
