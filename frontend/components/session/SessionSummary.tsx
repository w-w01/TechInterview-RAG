"use client";

import { useEffect, useMemo } from "react";
import confetti from "canvas-confetti";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { useReducedMotion } from "framer-motion";
import { Button, buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { ScoreDisplay } from "@/components/session/ScoreDisplay";
import type { GradingEntry, PaperQuestion } from "@/lib/types";
import { paperQuestionKey } from "@/lib/api";
import {
  Bar,
  BarChart,
  ResponsiveContainer,
  XAxis,
  YAxis,
} from "recharts";

type Props = {
  questions: PaperQuestion[];
  grading: Map<string, GradingEntry>;
  onRetry: () => void;
};

export function SessionSummary({ questions, grading, onRetry }: Props) {
  const t = useTranslations("session");
  const tc = useTranslations("common");
  const locale = useLocale();
  const reduceMotion = useReducedMotion();

  const scores = useMemo(() => {
    return questions.map((q, i) => {
      const entry = grading.get(paperQuestionKey(q));
      return {
        index: i + 1,
        score: entry?.result?.score ?? null,
        status: entry?.status ?? "pending",
        weak: entry?.result?.weak_topics ?? [],
      };
    });
  }, [questions, grading]);

  const doneScores = scores
    .map((s) => s.score)
    .filter((s): s is number => s !== null);
  const avg =
    doneScores.length > 0
      ? doneScores.reduce((a, b) => a + b, 0) / doneScores.length
      : 0;
  const best = doneScores.length > 0 ? Math.max(...doneScores) : 0;

  const weakCounts: Record<string, number> = {};
  scores.forEach((s) => {
    s.weak.forEach((w) => {
      weakCounts[w] = (weakCounts[w] ?? 0) + 1;
    });
  });
  const weakChart = Object.entries(weakCounts)
    .slice(0, 8)
    .map(([name, count]) => ({ name, count }));

  useEffect(() => {
    if (reduceMotion) return;
    if (avg >= 8 || (doneScores.length === questions.length && avg >= 6)) {
      confetti({
        particleCount: 120,
        spread: 70,
        origin: { y: 0.6 },
      });
    }
  }, [avg, doneScores.length, questions.length, reduceMotion]);

  return (
    <div className="space-y-6">
      <Card className="im-card border-0 shadow-none">
        <CardHeader>
          <CardTitle>{t("summaryTitle")}</CardTitle>
          <CardDescription>
            {avg >= 8 ? t("confettiHigh") : null}
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-6 sm:grid-cols-2">
          <div>
            <p className="text-sm text-muted-foreground">{t("avgScore")}</p>
            <p className="text-4xl font-semibold tabular-nums text-primary">
              <ScoreDisplay value={avg} />
              <span className="text-lg text-muted-foreground">/10</span>
            </p>
          </div>
          <div>
            <p className="text-sm text-muted-foreground">{t("bestScore")}</p>
            <p className="text-4xl font-semibold tabular-nums">
              <ScoreDisplay value={best} />
              <span className="text-lg text-muted-foreground">/10</span>
            </p>
          </div>
        </CardContent>
      </Card>

      <p className="text-xs text-muted-foreground">{tc("feedbackLocaleHint")}</p>

      {weakChart.length > 0 && (
        <Card className="im-card border-0 shadow-none">
          <CardHeader>
            <CardTitle className="text-base">{t("weakAreas")}</CardTitle>
          </CardHeader>
          <CardContent className="h-48">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={weakChart} layout="vertical" margin={{ left: 8 }}>
                <XAxis type="number" hide />
                <YAxis
                  type="category"
                  dataKey="name"
                  width={100}
                  tick={{ fontSize: 10 }}
                />
                <Bar dataKey="count" fill="#009A73" radius={4} />
              </BarChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      )}

      <Card className="im-card border-0 shadow-none">
        <CardHeader>
          <CardTitle className="text-base">{t("perQuestion")}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {scores.map((s) => (
            <details
              key={s.index}
              className="rounded-lg border border-border/50 bg-background/40 px-3 py-2"
            >
              <summary className="cursor-pointer text-sm font-medium">
                Q{s.index}{" "}
                {s.status === "done" && s.score !== null ? (
                  <span className="text-primary">{s.score}/10</span>
                ) : s.status === "scoring" ? (
                  <span className="text-muted-foreground">…</span>
                ) : s.status === "error" ? (
                  <span className="text-destructive">!</span>
                ) : (
                  <span className="text-muted-foreground">—</span>
                )}
              </summary>
              {s.status === "done" && (
                <div className="mt-2 space-y-2 text-xs text-muted-foreground">
                  {grading
                    .get(paperQuestionKey(questions[s.index - 1]))
                    ?.result?.strengths.map((x) => (
                      <p key={x}>+ {x}</p>
                    ))}
                </div>
              )}
            </details>
          ))}
        </CardContent>
      </Card>

      <div className="flex flex-wrap gap-3">
        <Button type="button" onClick={onRetry}>
          {t("retry")}
        </Button>
        <Link
          href={`/${locale}/learn`}
          className={cn(buttonVariants({ variant: "outline" }))}
        >
          {t("goLearn")}
        </Link>
      </div>
    </div>
  );
}
