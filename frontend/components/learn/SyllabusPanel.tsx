"use client";

import { AnimatePresence, motion } from "framer-motion";
import { useTranslations } from "next-intl";
import { Pencil, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { PlanSkeleton } from "@/components/learn/PlanSkeleton";
import { TagInput } from "@/components/learn/TagInput";
import { useLearn } from "@/components/learn/LearnProvider";
import { cn } from "@/lib/utils";

export function SyllabusPanel() {
  const t = useTranslations("learn");
  const {
    jdText,
    setJdText,
    weakTags,
    setWeakTags,
    planDays,
    setPlanDays,
    phase,
    learnPlan,
    planCards,
    loadingPlan,
    highlightedCardIds,
    pulseCardId,
    generatePlan,
    openEditConfig,
    onPlanCardClick,
  } = useLearn();

  return (
    <div className="learn-syllabus flex h-full max-h-full min-h-0 flex-col overflow-hidden rounded-3xl border border-border/80 bg-card shadow-[0_8px_32px_rgb(26_32_44/0.08)]">
      <div className="shrink-0 border-b border-border/70 px-5 py-3">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-dark-muted">
          {t("syllabusTitle")}
        </h2>
        <p className="mt-1 text-xs text-dark-light">{t("syllabusDesc")}</p>
      </div>

      <div className="flex min-h-0 flex-1 flex-col overflow-hidden px-5 pb-5 pt-4">
        <AnimatePresence mode="wait">
          {phase === "config" && (
            <motion.div
              key="config"
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -12 }}
              transition={{ duration: 0.35, ease: [0.22, 1, 0.36, 1] }}
              className="flex h-full min-h-0 flex-col gap-3"
            >
              <div className="min-h-0 flex-1 space-y-3 overflow-y-auto pr-0.5">
                <div className="flex flex-col gap-2">
                  <Label htmlFor="learn-jd">{t("jdLabel")}</Label>
                  <Textarea
                    id="learn-jd"
                    rows={4}
                    value={jdText}
                    onChange={(e) => setJdText(e.target.value)}
                    placeholder={t("jdPlaceholder")}
                    className="max-h-28 min-h-[5rem] resize-none rounded-xl border-border/80 bg-muted/25 font-mono text-sm leading-relaxed"
                  />
                </div>
                <div className="flex flex-col gap-2">
                  <Label htmlFor="learn-weak-tags">{t("weakLabel")}</Label>
                  <TagInput
                    id="learn-weak-tags"
                    tags={weakTags}
                    onChange={setWeakTags}
                    placeholder={t("weakPlaceholder")}
                  />
                </div>
                <div className="flex flex-col gap-2">
                  <Label htmlFor="plan-days">{t("planDays")}</Label>
                  <select
                    id="plan-days"
                    className="flex h-11 w-full rounded-xl border border-input bg-background px-3 text-sm shadow-xs outline-none focus-visible:border-primary focus-visible:ring-[3px] focus-visible:ring-primary/20"
                    value={planDays}
                    onChange={(e) =>
                      setPlanDays(
                        Math.min(
                          14,
                          Math.max(1, parseInt(e.target.value, 10) || 5),
                        ),
                      )
                    }
                  >
                    {Array.from({ length: 14 }, (_, i) => i + 1).map((n) => (
                      <option key={n} value={n}>
                        {t("dayOption", { n })}
                      </option>
                    ))}
                  </select>
                </div>
              </div>
              <div className="shrink-0 border-t border-border/60 pt-3">
                <Button
                  type="button"
                  className="h-11 w-full rounded-xl"
                  onClick={() => void generatePlan()}
                  disabled={loadingPlan || jdText.trim().length < 40}
                >
                  <Sparkles className="size-4" />
                  {loadingPlan ? t("generatingPlan") : t("generatePlan")}
                </Button>
              </div>
            </motion.div>
          )}

          {phase === "generating" && (
            <motion.div
              key="generating"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.3 }}
              className="h-full min-h-0 overflow-y-auto"
            >
              <p className="mb-4 text-sm text-dark-muted">{t("planGenerating")}</p>
              <PlanSkeleton />
            </motion.div>
          )}

          {phase === "timeline" && learnPlan && (
            <motion.div
              key="timeline"
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.4, ease: [0.22, 1, 0.36, 1] }}
              className="h-full min-h-0 space-y-5 overflow-y-auto pr-0.5"
            >
              <div className="flex items-center justify-between gap-2">
                <p className="text-sm font-semibold text-dark">
                  {learnPlan.plan_title}
                </p>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="shrink-0 rounded-full"
                  onClick={openEditConfig}
                >
                  <Pencil className="size-3.5" />
                  {t("editConfig")}
                </Button>
              </div>

              <div className="rounded-xl border border-amber-500/25 bg-amber-500/5 p-3 text-xs leading-relaxed text-dark-muted">
                <p className="font-medium text-amber-900">{t("jdPriority")}</p>
                <pre className="mt-2 whitespace-pre-wrap font-sans">
                  {learnPlan.jd_priority_guess_markdown}
                </pre>
              </div>

              <div className="learn-timeline relative space-y-0 pl-3">
                <div
                  className="absolute bottom-2 left-[7px] top-2 w-px bg-border"
                  aria-hidden
                />
                {learnPlan.days.map((day) => {
                  const dayCards = planCards.filter((c) => c.day === day.day);
                  const focusCard = dayCards.find((c) => c.kind === "focus");
                  const taskCards = dayCards.filter((c) => c.kind === "task");
                  return (
                    <div key={day.day} className="relative pb-6 last:pb-0">
                      <div
                        className="absolute left-0 top-2 size-3.5 rounded-full border-2 border-primary bg-background"
                        aria-hidden
                      />
                      <div className="ml-6 space-y-2">
                        {focusCard && (
                          <PlanCardButton
                            title={t("day", { n: day.day })}
                            subtitle={day.focus}
                            highlighted={highlightedCardIds.has(focusCard.id)}
                            pulsing={pulseCardId === focusCard.id}
                            onClick={() => onPlanCardClick(focusCard)}
                          />
                        )}
                        {taskCards.map((card) => (
                          <PlanCardButton
                            key={card.id}
                            title={card.label}
                            subtitle={
                              card.minutes
                                ? t("minutes", { n: card.minutes })
                                : undefined
                            }
                            highlighted={highlightedCardIds.has(card.id)}
                            pulsing={pulseCardId === card.id}
                            onClick={() => onPlanCardClick(card)}
                          />
                        ))}
                      </div>
                    </div>
                  );
                })}
              </div>

              {learnPlan.tips.length > 0 && (
                <ul className="list-disc space-y-1 pl-5 text-xs text-dark-muted">
                  {learnPlan.tips.map((tip) => (
                    <li key={tip}>{tip}</li>
                  ))}
                </ul>
              )}
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}

function PlanCardButton({
  title,
  subtitle,
  highlighted,
  pulsing,
  onClick,
}: {
  title: string;
  subtitle?: string;
  highlighted: boolean;
  pulsing: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "learn-plan-card w-full rounded-xl border-2 px-3 py-2.5 text-left transition-all duration-300",
        highlighted
          ? "border-primary bg-primary/10 shadow-[0_0_0_1px_rgb(0_154_115/0.2)]"
          : "border-border bg-background hover:border-primary/40 hover:bg-muted/40",
        pulsing && "learn-plan-card-pulse",
      )}
    >
      <p className="text-sm font-medium text-dark">{title}</p>
      {subtitle && (
        <p className="mt-0.5 text-xs text-dark-muted">{subtitle}</p>
      )}
    </button>
  );
}
