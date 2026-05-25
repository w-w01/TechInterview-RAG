"use client";

import { useMemo, useRef } from "react";
import { useLocale, useTranslations } from "next-intl";
import {
  AnimatePresence,
  motion,
  useReducedMotion,
} from "framer-motion";
import {
  ArrowLeftRight,
  FileText,
  Sparkles,
  Target,
  Tags,
  Wand2,
} from "lucide-react";
import type { AppLocale } from "@/i18n/routing";
import { DifficultySelect } from "@/components/session/DifficultySelect";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import type { Difficulty, SessionSource, TopicOption } from "@/lib/types";
import { groupTopicOptions } from "@/lib/topic-groups";
import { cn } from "@/lib/utils";

const DEMO_JD_ZH =
  "我们正在招聘高级后端工程师，要求熟悉 Python、分布式系统、数据库优化与系统设计。候选人需有 3 年以上经验，能独立完成服务开发与性能调优。";
const DEMO_JD_EN =
  "We are hiring a Senior Backend Engineer skilled in Python, distributed systems, databases, and system design. 3+ years experience required.";

const MODE_PANEL_MOTION = {
  initial: (dir: number) => ({
    opacity: 0,
    x: dir * 28,
    filter: "blur(6px)",
  }),
  animate: {
    opacity: 1,
    x: 0,
    filter: "blur(0px)",
  },
  exit: (dir: number) => ({
    opacity: 0,
    x: dir * -28,
    filter: "blur(6px)",
  }),
};

/** 根据 JD 文本给出轻量「智能识别」提示（纯前端启发式） */
function inferJdHint(
  text: string,
  locale: AppLocale,
): string | null {
  const t = text.trim().toLowerCase();
  if (t.length < 24) return null;
  const rules: { keys: string[]; zh: string; en: string }[] = [
    {
      keys: ["machine learning", "ml", "深度学习", "机器学习"],
      zh: "识别为机器学习 / AI 方向岗位",
      en: "Detected ML / AI role focus",
    },
    {
      keys: ["frontend", "react", "vue", "前端", "ui engineer"],
      zh: "识别为前端工程师岗位画像",
      en: "Detected front-end engineer profile",
    },
    {
      keys: ["devops", "sre", "kubernetes", "k8s", "运维"],
      zh: "识别为 DevOps / SRE 岗位画像",
      en: "Detected DevOps / SRE profile",
    },
    {
      keys: ["backend", "后端", "distributed", "分布式", "microservice"],
      zh: "识别为后端 / 分布式系统岗位",
      en: "Detected backend / distributed systems role",
    },
    {
      keys: ["full stack", "全栈"],
      zh: "识别为全栈工程师岗位",
      en: "Detected full-stack engineer role",
    },
    {
      keys: ["data engineer", "数据工程", "etl", "spark"],
      zh: "识别为数据工程方向",
      en: "Detected data engineering focus",
    },
  ];
  for (const rule of rules) {
    if (rule.keys.some((k) => t.includes(k))) {
      return locale === "zh" ? rule.zh : rule.en;
    }
  }
  if (t.length >= 40) {
    return locale === "zh"
      ? "已捕获职位要点，可开始 AI 组卷"
      : "Role signals captured — ready to build your paper";
  }
  return null;
}

export type SessionSetup = {
  source: SessionSource;
  jdText: string;
  count: number;
  difficulty: Difficulty;
  topics: string[];
  questionSource: "seed" | "llm";
};

type Props = {
  topicOptions: TopicOption[];
  setup: SessionSetup;
  onChange: (patch: Partial<SessionSetup>) => void;
  onStart: () => void;
  loading: boolean;
  demo?: boolean;
};

type ModeCardProps = {
  active: boolean;
  onClick: () => void;
  title: string;
  description: string;
  clickHint: string;
  icon: React.ReactNode;
};

function ModeCard({
  active,
  onClick,
  title,
  description,
  clickHint,
  icon,
}: ModeCardProps) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={active}
      data-active={active}
      className="session-mode-card group"
      onClick={onClick}
    >
      {!active && (
        <span className="pointer-events-none absolute right-5 top-5 rounded-full border border-primary/30 bg-background px-2.5 py-0.5 text-[0.6875rem] font-medium text-primary opacity-0 transition-opacity duration-200 group-hover:opacity-100">
          {clickHint}
        </span>
      )}
      <div className="flex w-full items-center gap-4">
        <span
          className={cn(
            "flex size-12 shrink-0 items-center justify-center rounded-2xl text-primary transition-colors duration-300",
            active ? "bg-primary/15" : "bg-muted group-hover:bg-primary/10",
          )}
        >
          {icon}
        </span>
        <span className="min-w-0 flex-1 text-left">
          <span className="block text-lg font-semibold leading-snug text-dark">
            {title}
          </span>
        </span>
      </div>
      <p className="pl-16 text-sm leading-relaxed text-dark-muted sm:pl-[4rem]">
        {description}
      </p>
    </button>
  );
}

export function SessionWizard({
  topicOptions,
  setup,
  onChange,
  onStart,
  loading,
  demo,
}: Props) {
  const locale = useLocale() as AppLocale;
  const t = useTranslations("session");
  const tc = useTranslations("common");
  const reduceMotion = useReducedMotion();
  const selectClass =
    "flex h-11 w-full rounded-xl border border-input bg-background px-3 py-2 text-sm shadow-xs outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50";

  const modeDirRef = useRef(1);

  const groupedTopics = useMemo(
    () => groupTopicOptions(topicOptions),
    [topicOptions],
  );

  const jdHint = useMemo(
    () => inferJdHint(setup.jdText, locale),
    [setup.jdText, locale],
  );

  const selectSource = (source: SessionSource) => {
    if (source !== setup.source) {
      modeDirRef.current = source === "topics" ? 1 : -1;
    }
    onChange({ source });
  };

  const panelTransition = reduceMotion
    ? { duration: 0.01 }
    : { duration: 0.42, ease: [0.22, 1, 0.36, 1] as const };

  const fillDemo = () => {
    onChange({
      source: "jd",
      jdText: locale === "en" ? DEMO_JD_EN : DEMO_JD_ZH,
      count: 5,
    });
  };

  const toggleTopic = (slug: string) => {
    const has = setup.topics.includes(slug);
    const next = has
      ? setup.topics.filter((s) => s !== slug)
      : [...setup.topics, slug];
    onChange({
      topics: next.length ? next : setup.topics,
    });
  };

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-10 py-4">
      <header className="space-y-3 text-center sm:text-left">
        <h1 className="text-3xl font-semibold tracking-tight text-dark sm:text-4xl">
          {t("title")}
        </h1>
        <p className="max-w-2xl text-base text-dark-muted">{t("subtitleFlow")}</p>
      </header>

      {/* 模式切换提示 + 大卡片 */}
      <div className="flex w-full flex-col gap-4">
        <p className="flex w-full items-center justify-center gap-2 text-sm text-dark-muted sm:justify-start">
          <ArrowLeftRight className="size-4 shrink-0 text-primary" aria-hidden />
          <span>{t("modeSwitchHint")}</span>
        </p>
        <div
          className="grid w-full gap-4 sm:grid-cols-2 sm:gap-5"
          role="radiogroup"
          aria-label={t("modeSelectLabel")}
        >
          <ModeCard
            active={setup.source === "jd"}
            onClick={() => selectSource("jd")}
            title={t("modeAiTitle")}
            description={t("modeAiDesc")}
            clickHint={t("modeClickHint")}
            icon={
              <span className="flex items-center gap-0.5">
                <Wand2 className="size-6" strokeWidth={1.75} />
                <FileText className="size-4" strokeWidth={1.75} />
              </span>
            }
          />
          <ModeCard
            active={setup.source === "topics"}
            onClick={() => selectSource("topics")}
            title={t("modeTopicsTitle")}
            description={t("modeTopicsDesc")}
            clickHint={t("modeClickHint")}
            icon={
              <span className="flex items-center gap-0.5">
                <Target className="size-6" strokeWidth={1.75} />
                <Tags className="size-4" strokeWidth={1.75} />
              </span>
            }
          />
        </div>
      </div>

      {/* 动态内容：统一外壳 + crossfade 切换 */}
      <div className="session-dynamic-shell">
        <AnimatePresence mode="wait" custom={modeDirRef.current}>
          {setup.source === "jd" ? (
            <motion.section
              key="jd-panel"
              custom={modeDirRef.current}
              variants={reduceMotion ? undefined : MODE_PANEL_MOTION}
              initial={reduceMotion ? false : "initial"}
              animate="animate"
              exit="exit"
              transition={panelTransition}
              className="space-y-4"
              aria-labelledby="jd-editor-heading"
            >
              <div className="flex flex-wrap items-end justify-between gap-3">
                <div>
                  <h2
                    id="jd-editor-heading"
                    className="text-sm font-medium uppercase tracking-wider text-dark-muted"
                  >
                    {t("jdEditorTitle")}
                  </h2>
                  <p className="mt-1 text-sm text-dark-light">
                    {t("jdEditorHint")}
                  </p>
                </div>
                {demo && (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={fillDemo}
                  >
                    {t("demoJdFilled")}
                  </Button>
                )}
              </div>

              <div className="relative">
                <AnimatePresence>
                  {jdHint && (
                    <motion.div
                      key={jdHint}
                      initial={{ opacity: 0, y: -6 }}
                      animate={{ opacity: 1, y: 0 }}
                      exit={{ opacity: 0, y: -4 }}
                      transition={{ duration: 0.28 }}
                      className="session-smart-hint absolute -top-3 right-4 z-10 flex items-center gap-2 rounded-full border border-primary/25 bg-background px-3 py-1.5 text-xs font-medium text-primary shadow-sm"
                      role="status"
                    >
                      <Sparkles className="size-3.5 shrink-0" aria-hidden />
                      {jdHint}
                    </motion.div>
                  )}
                </AnimatePresence>
                <Textarea
                  rows={10}
                  value={setup.jdText}
                  onChange={(e) => onChange({ jdText: e.target.value })}
                  placeholder={t("jdPlaceholderMd")}
                  className={cn(
                    "min-h-[220px] w-full resize-y rounded-2xl border-border/80 bg-muted/30 font-mono text-[0.9375rem] leading-relaxed shadow-inner",
                    "focus-visible:border-primary/40 focus-visible:ring-primary/20",
                  )}
                />
              </div>
              <p className="text-xs text-dark-light">{t("jdMinHint")}</p>
            </motion.section>
          ) : (
            <motion.section
              key="topics-panel"
              custom={modeDirRef.current}
              variants={reduceMotion ? undefined : MODE_PANEL_MOTION}
              initial={reduceMotion ? false : "initial"}
              animate="animate"
              exit="exit"
              transition={panelTransition}
              className="space-y-8"
              aria-labelledby="topics-grid-heading"
            >
              <div>
                <h2
                  id="topics-grid-heading"
                  className="text-sm font-medium uppercase tracking-wider text-dark-muted"
                >
                  {t("topicsGridTitle")}
                </h2>
                <p className="mt-1 text-sm text-dark-light">
                  {t("topicsGridHint")}
                </p>
              </div>

              {groupedTopics.map(({ groupId, items }) => (
                <div key={groupId} className="space-y-4">
                  <h3 className="text-base font-semibold text-dark">
                    {t(`topicGroup_${groupId}`)}
                  </h3>
                  <div className="grid w-full gap-3 sm:grid-cols-2 lg:grid-cols-3">
                    {items.map((opt) => {
                      const active = setup.topics.includes(opt.slug);
                      return (
                        <button
                          key={opt.slug}
                          type="button"
                          aria-pressed={active}
                          onClick={() => toggleTopic(opt.slug)}
                          className={cn(
                            "rounded-2xl border-2 px-4 py-4 text-left text-sm font-medium transition-all duration-200",
                            active
                              ? "border-primary bg-primary/[0.08] text-dark shadow-[0_8px_24px_rgb(0_154_115/0.12)]"
                              : "border-border bg-background text-dark-muted hover:border-primary/30 hover:text-dark",
                          )}
                        >
                          {opt.label}
                        </button>
                      );
                    })}
                  </div>
                </div>
              ))}
            </motion.section>
          )}
        </AnimatePresence>
      </div>

      {/* 底部场次设置：两种模式共用，全宽 */}
      <section
        className="w-full rounded-3xl border border-border bg-muted/25 p-6 sm:p-8"
        aria-labelledby="session-settings-heading"
      >
        <h2
          id="session-settings-heading"
          className="mb-6 text-sm font-medium uppercase tracking-wider text-dark-muted"
        >
          {t("sessionSettingsTitle")}
        </h2>

        <div className="flex w-full flex-col gap-6">
          <div className="grid w-full grid-cols-1 gap-6 sm:grid-cols-2">
            <div className="flex w-full flex-col gap-2">
              <Label htmlFor="session-difficulty">{tc("difficulty")}</Label>
              <DifficultySelect
                id="session-difficulty"
                value={setup.difficulty}
                onChange={(difficulty) => onChange({ difficulty })}
                disabled={loading}
              />
            </div>
            <div className="flex w-full flex-col gap-2">
              <Label htmlFor="session-count">{t("questionCount")}</Label>
              <input
                id="session-count"
                type="number"
                min={1}
                max={20}
                className={selectClass}
                value={setup.count}
                onChange={(e) =>
                  onChange({
                    count: Math.min(
                      20,
                      Math.max(1, parseInt(e.target.value, 10) || 1),
                    ),
                  })
                }
              />
            </div>
          </div>

          {setup.source === "topics" && (
            <div className="flex w-full flex-col gap-3 border-t border-border/70 pt-6 sm:flex-row sm:flex-wrap sm:items-center sm:gap-8">
              <span className="text-sm font-medium text-dark-muted">
                {t("questionSource")}
              </span>
              <div className="flex flex-wrap gap-6">
                <label className="flex cursor-pointer items-center gap-2 text-sm">
                  <input
                    type="radio"
                    name="questionSource"
                    checked={setup.questionSource === "seed"}
                    onChange={() => onChange({ questionSource: "seed" })}
                    className="accent-primary"
                  />
                  {t("sourceSeed")}
                </label>
                <label className="flex cursor-pointer items-center gap-2 text-sm">
                  <input
                    type="radio"
                    name="questionSource"
                    checked={setup.questionSource === "llm"}
                    onChange={() => onChange({ questionSource: "llm" })}
                    className="accent-primary"
                  />
                  {t("sourceLlm")}
                </label>
              </div>
            </div>
          )}

          <Button
            type="button"
            size="lg"
            className="h-12 w-full rounded-xl text-base"
            disabled={
              loading ||
              (setup.source === "topics" && setup.topics.length === 0) ||
              (setup.source === "jd" && setup.jdText.trim().length < 40)
            }
            onClick={onStart}
          >
            {loading
              ? setup.source === "jd"
                ? t("building")
                : t("generating")
              : t("startSession")}
          </Button>
        </div>
      </section>
    </div>
  );
}
