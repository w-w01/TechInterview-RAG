# 题库数据格式（当前版本）

## 文件位置与编码

- 默认路径：`backend/data/interview_qa_seed.json`
- 编码：**UTF-8**
- 顶层结构：**JSON 数组**，数组中每个元素为一道题的 **对象**

## 每条记录（必填 / 可选）

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `id` | string | 是 | 全局唯一，与 `/generate-question` 返回的 `question_id`、`/evaluate-answer` 的请求字段一致 |
| `topics` | string[] | 是 | **至少 1 个** topic slug；可多标签表示一题跨类；每个 slug 必须在 `backend/data/topic_allowlist.json` 中定义 |
| `difficulty` | string | 是 | `beginner` \| `intermediate` \| `advanced` |
| `question` | string | 是 | 题干 |
| `answer` | string | 是 | 参考答案（写入评卷 prompt 与引用片段） |
| `key_points` | string[] | 建议 | 可为 `[]`；用于出题「期望要点」与评卷 prompt |
| `tags` | string[] | 否 | 仅占位/自用，后端逻辑不读取 |
| `source` | string | 否 | 引用展示来源说明；缺省时后端写默认文案 |

## Topic slug 与白名单

- 合法 slug 由 **`backend/data/topic_allowlist.json`** 统一管理（含 `slug` + `label`）。
- **当前仓库**：白名单与 `interview_qa_seed.json` 由脚本从公开数据集生成（见下）；共约 **21** 个 slug（如 `algorithms`、`system_design`、`devops`、`front_end`、`database_and_sql` 等，以生成结果为准）。
- 扩充类目：可改脚本映射或手工编辑白名单 + 种子，并重启后端；种子里只允许出现白名单中的 slug。

## 从官方 JSON 重新生成种子与白名单

- 源文件：`backend/data/kaggle-Software_Engineering_Interview_Questions_Dataset.json`（`{"results":[...]}`）。
- 执行：

```powershell
cd backend
python scripts\etl_kaggle_to_seed.py
```

会**覆盖** `interview_qa_seed.json` 与 `topic_allowlist.json`。

- **规范化**：原始类目字符串小写、笔误合并后，空格与连字符转为下划线得到 slug（示例：`system design` → `system_design`）。

## 选题规则（与 UI 对应）

- 请求中带 `topics: string[]`（用户勾选），与题目的 `topics` **至少有一个 slug 相同（集合交集非空）**，且 `difficulty` 一致，进入候选池再随机抽题。

## CSV / Kaggle 映射示例

源列例如：`question_id`, `q`, `a`, `category`, `difficulty`：

- `question_id` → `id`
- `q` → `question`，`a` → `answer`
- `category` → 映射到白名单中的 slug 填入 `topics`（可多列合并为多标签）
- `difficulty` → 映射到 `beginner` / `intermediate` / `advanced`
- 若无要点列：`key_points` 设为 `[]`
