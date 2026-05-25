"use client";

import { useCallback } from "react";
import {
  AnimatePresence,
  motion,
  useMotionValue,
  useReducedMotion,
  useTransform,
} from "framer-motion";
import { useTranslations } from "next-intl";
import { Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import type { GradingEntry, PaperQuestion } from "@/lib/types";
import { paperQuestionKey } from "@/lib/api";

type Props = {
  questions: PaperQuestion[];
  currentIndex: number;
  answers: Record<string, string>;
  grading: Map<string, GradingEntry>;
  onAnswerChange: (key: string, text: string) => void;
  onNext: () => void;
  isLast: boolean;
};

const SWIPE_THRESHOLD = 80;

export function QuestionDeck({
  questions,
  currentIndex,
  answers,
  grading,
  onAnswerChange,
  onNext,
  isLast,
}: Props) {
  const t = useTranslations("session");
  const reduceMotion = useReducedMotion();
  const q = questions[currentIndex];
  const key = q ? paperQuestionKey(q) : "";
  const dragX = useMotionValue(0);
  const opacity = useTransform(dragX, [-120, 0, 120], [0.6, 1, 0.6]);

  const handleDragEnd = useCallback(
    (_: unknown, info: { offset: { x: number } }) => {
      if (info.offset.x < -SWIPE_THRESHOLD) {
        onNext();
      }
      dragX.set(0);
    },
    [onNext, dragX],
  );

  if (!q) return null;

  const prevKey =
    currentIndex > 0
      ? paperQuestionKey(questions[currentIndex - 1])
      : null;
  const prevGrading = prevKey ? grading.get(prevKey) : null;

  return (
    <div className="flex flex-col gap-6 lg:flex-row">
      <aside className="hidden w-48 shrink-0 flex-col gap-2 lg:flex">
        {questions.map((_, i) => (
          <div
            key={i}
            className={`rounded-lg border px-3 py-2 text-xs ${
              i < currentIndex
                ? "border-primary/40 bg-primary/10 text-primary"
                : i === currentIndex
                  ? "border-accent bg-accent/10 text-accent-foreground"
                  : "border-border/40 text-muted-foreground"
            }`}
          >
            {i + 1}
            {i < currentIndex && grading.get(paperQuestionKey(questions[i]))?.status === "scoring" && (
              <Loader2 className="ml-1 inline size-3 animate-spin" />
            )}
          </div>
        ))}
      </aside>

      <div className="min-w-0 flex-1">
        <p className="mb-2 text-sm text-muted-foreground">
          {t("progress", { current: currentIndex + 1, total: questions.length })}
        </p>
        <div className="mb-2 h-1.5 overflow-hidden rounded-full bg-muted">
          <div
            className="h-full bg-brand transition-all duration-300"
            style={{
              width: `${((currentIndex + 1) / questions.length) * 100}%`,
            }}
          />
        </div>

        <AnimatePresence mode="wait">
          <motion.div
            key={key}
            style={reduceMotion ? undefined : { x: dragX, opacity }}
            drag={reduceMotion ? false : "x"}
            dragConstraints={{ left: 0, right: 0 }}
            dragElastic={0.15}
            onDragEnd={handleDragEnd}
            initial={reduceMotion ? false : { opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            exit={reduceMotion ? undefined : { opacity: 0, x: -40 }}
            transition={{ duration: 0.22 }}
          >
            <Card className="im-card border-0 shadow-none">
              <CardHeader>
                <CardTitle className="text-base font-medium leading-relaxed">
                  {q.question}
                </CardTitle>
                <p className="text-xs text-muted-foreground">
                  {q.topics.join(" · ")} / {q.difficulty}
                </p>
              </CardHeader>
              <CardContent className="space-y-4">
                <Textarea
                  rows={8}
                  value={answers[key] ?? ""}
                  onChange={(e) => onAnswerChange(key, e.target.value)}
                  placeholder={t("answerPlaceholder")}
                  className="bg-background/50"
                />
              </CardContent>
            </Card>
          </motion.div>
        </AnimatePresence>

        {prevGrading?.status === "scoring" && (
          <p className="mt-2 flex items-center gap-2 text-xs text-muted-foreground">
            <Loader2 className="size-3 animate-spin" />
            {t("grading")}…
          </p>
        )}

        <p className="mt-2 text-xs text-muted-foreground">{t("noBack")}</p>

        <div className="sticky bottom-4 z-10 mt-6 flex justify-end md:static">
          <Button type="button" size="lg" onClick={onNext} className="w-full sm:w-auto">
            {isLast ? t("submitSession") : t("nextQuestion")}
          </Button>
        </div>
      </div>
    </div>
  );
}
