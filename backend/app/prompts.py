"""大模型评估用的系统提示与 rubric 说明（中文指令便于简历演示）。"""

from typing import List

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

必须只输出一个 JSON 对象，字段为：
score, strengths, missing_points, improved_answer
其中 strengths 与 missing_points 为字符串数组。"""


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
