/** Topic 宫格聚类：slug 与后端 topic_allowlist.json 对齐 */
export type TopicGroupId = "foundations" | "engineering" | "frontier";

export const TOPIC_GROUP_SLUGS: Record<TopicGroupId, string[]> = {
  foundations: [
    "algorithms",
    "data_structures",
    "general_programming",
    "networking",
    "low_level_systems",
    "database_and_sql",
    "database_systems",
    "version_control",
  ],
  engineering: [
    "back_end",
    "front_end",
    "devops",
    "full_stack",
    "web_development",
    "distributed_systems",
    "system_design",
    "data_engineering",
    "languages_and_frameworks",
    "security",
    "software_testing",
  ],
  frontier: ["artificial_intelligence", "machine_learning"],
};

export const TOPIC_GROUP_ORDER: TopicGroupId[] = [
  "foundations",
  "engineering",
  "frontier",
];

/** 将 API 返回的 topics 按聚类分组，未命中白名单的归入 engineering */
export function groupTopicOptions(
  options: { slug: string; label: string }[],
): { groupId: TopicGroupId; items: { slug: string; label: string }[] }[] {
  const bySlug = new Map(options.map((o) => [o.slug, o]));
  const assigned = new Set<string>();
  const result: {
    groupId: TopicGroupId;
    items: { slug: string; label: string }[];
  }[] = [];

  for (const groupId of TOPIC_GROUP_ORDER) {
    const items: { slug: string; label: string }[] = [];
    for (const slug of TOPIC_GROUP_SLUGS[groupId]) {
      const opt = bySlug.get(slug);
      if (opt) {
        items.push(opt);
        assigned.add(slug);
      }
    }
    if (items.length) result.push({ groupId, items });
  }

  const rest = options.filter((o) => !assigned.has(o.slug));
  if (rest.length) {
    const eng = result.find((g) => g.groupId === "engineering");
    if (eng) eng.items.push(...rest);
    else result.push({ groupId: "engineering", items: rest });
  }

  return result;
}
