"""大模型评估与 AI 出题用的系统提示（中文指令便于简历演示）。"""

from typing import Any, Dict, List

EVALUATION_SYSTEM_PROMPT = """你是技术面试考官助手。根据「参考材料」中的要点与用户答案，按 rubric 输出严格 JSON，不要输出 markdown 代码块。

Rubric（每项独立判断）：
1. 技术准确性：与参考材料一致得高分；明显错误扣分。
2. 覆盖面：是否覆盖 key_points 中的主要概念。
3. 表达清晰度：结构是否清楚（不要求长篇）。

评分规则：
- score 为 0-10 的整数。
- strengths：用户答对或表述到位的点，2-4 条短句。
- missing_points：相对参考材料遗漏或错误的点，2-5 条短句。
- improved_answer：一段精炼的示范回答（可整合参考材料），中文为主，必要时保留英文术语。
- weak_topics：从本次作答识别出的薄弱知识点关键词，2-5 条短语（小写、便于后续补弱组卷）。

必须只输出一个 JSON 对象，字段为：
score, strengths, missing_points, improved_answer, weak_topics
其中 strengths、missing_points、weak_topics 为字符串数组。"""


def build_evaluation_user_prompt(
    *,
    topics: List[str],
    difficulty: str,
    question: str,
    student_answer: str,
    reference_block: str,
    key_points_block: str,
) -> str:
    topics_line = ", ".join(topics) if topics else "(无)"
    return f"""主题（标签）: {topics_line}
难度: {difficulty}

面试问题:
{question}

考生答案:
{student_answer}

本题参考要点（key_points）:
{key_points_block}

本题题库参考答案（canonical，可引用其技术事实）:
{reference_block}

请严格按系统说明输出 JSON。"""


GENERATION_SYSTEM_PROMPT = """你是技术面试命题助手。根据给定的主题标签、难度与参考题库样例（若有），命制一道**新的**面试题：不得复制样例题干原文，可考查相同知识域的不同角度。

输出要求：
- 必须只输出一个 JSON 对象，不要 markdown 代码块。
- 字段 question：题干字符串，清晰可答；技术术语可中英并存。
- 字段 expected_key_points：字符串数组，3-8 条，为评分用的期望要点（短句）。

若无样例（零样本），仅依据标签与难度命制常见技术面试题。"""


def build_generation_user_prompt(
    *,
    topics: List[str],
    difficulty: str,
    reference_items: List[Dict[str, Any]],
) -> str:
    """构造 AI 出题的用户消息；reference_items 为种子条目 dict 列表，可能为空。"""
    topics_line = ", ".join(topics) if topics else "(无)"
    blocks: List[str] = [
        f"主题（标签）: {topics_line}",
        f"难度: {difficulty}",
    ]
    if reference_items:
        blocks.append("参考题库样例（仅供风格与知识点参考，请命制不同题干）：")
        for i, it in enumerate(reference_items, start=1):
            q = str(it.get("question", "")).strip()
            a = str(it.get("answer", "")).strip()
            kp = it.get("key_points") or []
            kp_lines = (
                "\n".join(f"  - {p}" for p in kp)
                if isinstance(kp, list)
                else str(kp)
            )
            blocks.append(
                f"--- 样例 {i} ---\n题干: {q}\n参考答案摘要: {a[:1200]}\n要点:\n{kp_lines}"
            )
    else:
        blocks.append("当前标签与难度下题库无条目，请零样本命制一题。")
    blocks.append("请输出 JSON：question, expected_key_points（数组）。")
    return "\n\n".join(blocks)
