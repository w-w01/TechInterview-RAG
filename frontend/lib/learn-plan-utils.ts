import type { TutorPlanResponse } from "@/lib/types";

/** 左侧看板可点击 / 可高亮的知识点卡片 */
export type PlanCard = {
  id: string;
  day: number;
  kind: "focus" | "task";
  label: string;
  minutes?: number;
};

export function buildPlanCards(plan: TutorPlanResponse): PlanCard[] {
  const cards: PlanCard[] = [];
  for (const d of plan.days) {
    cards.push({
      id: `day-${d.day}-focus`,
      day: d.day,
      kind: "focus",
      label: d.focus,
    });
    d.tasks.forEach((task, i) => {
      cards.push({
        id: `day-${d.day}-task-${i}`,
        day: d.day,
        kind: "task",
        label: task.task,
        minutes: task.estimated_minutes,
      });
    });
  }
  return cards;
}

/** 从计划卡片提取用于 Tutor 流式高亮匹配的关键词（越长越优先） */
export function keywordsFromPlanCards(cards: PlanCard[]): string[] {
  const raw = cards
    .map((c) => c.label.trim())
    .filter((s) => s.length >= 3);
  return [...raw].sort((a, b) => b.length - a.length);
}

/** 在 Tutor 回复文本中扫描命中的卡片 id */
export function matchHighlightedCardIds(
  text: string,
  cards: PlanCard[],
): string[] {
  const lower = text.toLowerCase();
  const hit: string[] = [];
  for (const card of cards) {
    const kw = card.label.trim();
    if (kw.length >= 3 && lower.includes(kw.toLowerCase())) {
      hit.push(card.id);
    }
  }
  return hit;
}

export function weakTopicForApi(tags: string[]): string {
  return tags.map((t) => t.trim()).filter(Boolean).join("，");
}
