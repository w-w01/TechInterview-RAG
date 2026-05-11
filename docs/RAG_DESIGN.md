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

## 多语言与答复语言控制（设计）

面向 **单用户、中英双语者、提问中英夹杂、知识库中英混杂** 的场景；与现有 **topic 白名单仍为英文 `slug`**、**题库 seed 以英文题干为主** 的现状兼容。

### 分层策略

1. **会话级偏好（主开关）**  
   - 建议字段：`locale_mode` ∈ `auto` | `zh` | `en` | `mixed`（默认 `auto`）。  
   - `mixed`：生成侧采用固定双语结构（例如先中文概要再 English，或与现有评卷里「中文 / English」示范段落对齐）。  
   - 单用户可在前端提供极简切换，或请求体/query 显式传入以覆盖自动检测。

2. **轮次级检测（仅当 `locale_mode === auto`）**  
   - 输入：本轮用户消息（及可选的上一轮助手语言）。  
   - 启发式：CJK 字符占比超阈值 → 倾向中文；否则拉丁词形占比高 → 倾向英文；两者均高 → 记为 **code-switch（夹杂）**。  
   - 不必强依赖 LLM 做语言分类；必要时再增加轻量分类器。

3. **知识库检索（规划中的 Knowledge RAG）**  
   - 每个 chunk 的 metadata 增加 **`lang`** 或 **`primary_lang`**：`zh` | `en` | `mixed`。  
   - `auto`：**先按检测语言过滤** Top‑K；若得分偏低或条数不足，**放宽过滤**（例如并入 `mixed` 或全库再搜一轮）。  
   - **夹杂提问**：可对中英各取一部分配额（并行两路或单次检索后对 chunk 做语言均衡重排）。  
   - **向量模型**：与题库 JD 检索一致可采用 `text-embedding-3-small`，支持多语种语义相近召回；**跨语言对齐**（如中文 JD + 英文题干）可能弱于同语种，属预期现象。

4. **生成侧（Tutor / 讲解 / 推荐阅读文案）**  
   - 根据 `locale_mode` 与检测结果注入系统指令：**主体语种**、术语是否保留英文、夹杂时是否采用 `mixed` 模板。  
   - **引用片段（citations）**：保留原文语种，外层说明句跟随答复语种。

### 与现有链路的关系

- **评卷主链路**：仍只使用本题 **canonical / `generation_id` 快照**；多语言控制 **不默认** 把知识库检索结果写入评卷 prompt（与下文 Knowledge RAG 边界一致）。  
- **JD 组卷**：仍为向量检索英文 seed + Planner/Selector；用户 JD 可为中文，无需为「纯英文知识库」而删中文资料。  
- **数据文件编码**：原始资料与 API 交换统一 **UTF-8**（见 [DATA_SCHEMA.md](DATA_SCHEMA.md) 题库约定）。

## 后续可改进方向

- JD 经 LLM 压缩为查询向量或与关键词检索混合。
- 题目在检索约束下的生成并做安全过滤。
- 评估指标与人工标注对齐。
- “已答过”集合当前按 `score != null` 定义，可扩展为“已展开/已作答未评估”亦计入，避免用户中断后重复。

## LangChain 知识库 RAG 规划

当前文件中的 **JD RAG** 面向“组卷”：检索对象是面试题 seed，目标是为 Planner / Selector 提供候选题。后续若接入自有 IT 面试“八股”文章，建议新增独立的 **Knowledge RAG**，面向“学习”：检索对象是知识文章 chunk，目标是解释、推荐、学习计划与复测。

## LangChain 知识库 RAG（当前实现）

`/sessions/{session_id}/tutor/chat` 已接入统一知识库检索问答链路，核心如下：

1. **索引对象**：`backend/data/knowledge/documents/**.json`（不拆中英文库）。
2. **分块**：`RecursiveCharacterTextSplitter` 按标题/段落优先切分；**每个分块在嵌入前拼接 `Title: {title}` 与正文**，使标题概括与查询语义对齐（非单独关键词倒排，仍是向量检索）。
3. **向量库**：OpenAI `text-embedding-3-small` + 本地 `FAISS`（进程启动构建）。
4. **问答链**：LangChain `create_stuff_documents_chain`（stuff）。
5. **查询前处理**：全 LLM `query rewrite`（意图识别 + 改写），支持：
   - `context_dependent`
   - `comparison`
   - `pronoun_ambiguous`
   - `multi_intent`
   - `rhetorical`
   - `direct`
6. **子库过滤**：请求可带 `corpus_id`（与落盘子目录一致）；**不按 `topic_slugs` 过滤**——该字段主要服务题库白名单，知识库元数据易与文章实际主题不一致。
7. **语言策略**：单次检索，不做失败后二次跨语言重搜；依赖多语 embedding 的跨语种语义相似能力。保留 `lang` metadata 便于后续升级。
8. **返回信息**：除回复正文外，附带 `query_type`、`rewritten_query`、`retrieval_queries`、`retrieved_chunks`、`rewrite_confidence` 与文档 `citations`。调试可用 `POST /knowledge/search`。

### 知识库数据流（规划）

1. **资料入口**：将 Markdown / txt / HTML 等文章放入独立目录（例如 `backend/data/knowledge_raw/`），保留原始来源。
2. **ETL 清洗**：脚本抽取标题、正文、代码块、来源、标签；人工或规则映射到现有 topic 白名单。
3. **LangChain 分块**：使用文档加载器与 `RecursiveCharacterTextSplitter`，尽量按标题层级切分，避免把不同概念混在同一 chunk。
4. **Metadata**：每个 chunk 至少保留 `chunk_id`、`title`、`source`、`topic_slug`、`tags`、`difficulty`、`section_path`、**`lang`（或 `primary_lang`：zh / en / mixed）** 等字段，便于引用、过滤与多语言检索重排（见上文「多语言与答复语言控制」）。
5. **向量索引**：先用本地 FAISS / Chroma + OpenAI Embeddings；知识库索引与现有 `seed_embedding_index` 分离。
6. **检索 API**：已实现 `POST /knowledge/search`（`query`、`top_k`、可选 `corpus_id`），输出 snippets + metadata。

### 可接入功能（规划）

- **Tutor 引用式答疑**：Tutor 根据用户问题 / `weak_topic` 检索知识库，把 snippets 注入 prompt，并在响应中返回 citations。
- **评卷后推荐阅读**：`/evaluate-answer` 输出 `study_topics` 后，通过知识库检索推荐相关文章片段，作为“下一步学习”展示。
- **学习计划资料绑定**：`/tutor/learning-plan` 在 JD 侧重点推断后检索相关资料，为每天任务附阅读材料、复述任务与小测建议。
- **薄弱点复测**：从知识库相关 chunk 生成小测题，用于学习后的复盘；此类题应明确标记为知识库生成题。

### 边界原则

- **不要默认把 Knowledge RAG 放入评卷 prompt**。现有评卷锚定 canonical / generation snapshot，是评分稳定性与可追溯性的核心设计。
- 知识库可以用于**评卷后的解释、推荐与学习**；若未来用于出题，应在题目来源中明确标记为 `knowledge` 或类似来源。
- LangChain 主要承担文档加载、分块、向量库与检索链路；JD Planner / Selector 的程序校验与业务约束仍保留自定义实现。

## 流式输出

### Tutor（已实现，P0）

- **路由**：`POST /sessions/{session_id}/tutor/chat/stream`，响应 `text/event-stream`（SSE）。**一次性 JSON** 仍保留：`POST .../tutor/chat`（`backend/app/main.py` 中 `tutor_chat`）。
- **载荷**：每帧 `data: <JSON>\n\n`，`type` 为 `meta`（RAG 路径：引用与 query 改写元数据） / `delta`（`text` 正文增量） / `done`（`suggested_followups`） / `error`。
- **后端**：RAG 路径在流式前完成 query 改写与检索；正文由 LangChain stuff 链 `astream` 或 OpenAI `stream=True`（非 RAG）写出。详见 `KnowledgeRAGService.stream_answer_with_stuff`、`tutor_chat_stream`。
- **前端**：`frontend/app/page.tsx` 中 `onTutorSend` 使用 **`fetch` + `ReadableStream`** 解析 SSE（非 `EventSource`，因请求体为 POST JSON）。首 token 前保留「正在回复」态；助手气泡正文由 **`react-markdown`**（`components/tutor-markdown.tsx`，GFM + `rehype-sanitize`）渲染。

### 仍为非流式 / 规划中

| 优先级 | 场景 | 路由 / 代码 | 说明 |
|--------|------|------------|------|
| **P1** | 学习计划长文 | `POST /sessions/{session_id}/tutor/learning-plan` | 可对 `jd_priority_guess_markdown` 等做流式；当前仍为完整 JSON。 |
| **P2** | 评卷反馈长文 | `POST /evaluate-answer` | 强依赖完整 JSON；若要做流式需拆分结构化字段与讲解文本。 |
| **暂缓** | AI 出题、JD Planner、JD Selector | 若干 `generate-*` / JD 路由 | 强依赖 JSON，流式收益低。 |
