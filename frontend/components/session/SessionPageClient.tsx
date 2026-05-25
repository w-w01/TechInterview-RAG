"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { Loader2 } from "lucide-react";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { SessionWizard, type SessionSetup } from "@/components/session/SessionWizard";
import { QuestionDeck } from "@/components/session/QuestionDeck";
import { SessionSummary } from "@/components/session/SessionSummary";
import {
  buildEvaluatePayload,
  createSession,
  evaluateAnswer,
  fetchTopics,
  generatePaperFromJd,
  generateQuestionLlm,
  generateQuestionSeed,
  paperQuestionKey,
} from "@/lib/api";
import {
  GRADING_CONCURRENCY,
  createGradingEntry,
  setGradingDone,
  setGradingError,
  setGradingScoring,
  type GradingStore,
} from "@/lib/session-store";
import type { GradingEntry, PaperQuestion, TopicOption } from "@/lib/types";

type Step = "setup" | "deck" | "summary";

export function SessionPageClient() {
  const t = useTranslations("session");
  const te = useTranslations("errors");
  const tc = useTranslations("common");
  const searchParams = useSearchParams();
  const isDemo = searchParams.get("demo") === "1";

  const [step, setStep] = useState<Step>("setup");
  const [topicOptions, setTopicOptions] = useState<TopicOption[]>([]);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [questions, setQuestions] = useState<PaperQuestion[]>([]);
  const [currentIndex, setCurrentIndex] = useState(0);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [grading, setGrading] = useState<GradingStore>(() => new Map());
  const [setup, setSetup] = useState<SessionSetup>({
    source: "jd",
    jdText: "",
    count: 5,
    difficulty: "intermediate",
    topics: ["general_programming"],
    questionSource: "llm",
  });

  const gradingRef = useRef(grading);
  const queueRef = useRef<string[]>([]);
  const activeRef = useRef(0);
  const sessionIdRef = useRef<string | null>(null);

  useEffect(() => {
    gradingRef.current = grading;
  }, [grading]);

  useEffect(() => {
    sessionIdRef.current = sessionId;
  }, [sessionId]);

  useEffect(() => {
    fetchTopics().then((topics) => {
      if (topics.length) {
        setTopicOptions(topics);
        setSetup((s) => ({
          ...s,
          topics: s.topics.filter((slug) =>
            topics.some((t) => t.slug === slug),
          ).length
            ? s.topics.filter((slug) => topics.some((t) => t.slug === slug))
            : [topics[0].slug],
        }));
      }
    });
    createSession().then(setSessionId);
  }, []);

  const patchGrading = useCallback(
    (updater: (m: GradingStore) => void) => {
      setGrading((prev) => {
        const next = new Map(prev);
        updater(next);
        gradingRef.current = next;
        return next;
      });
    },
    [],
  );

  const runEvaluate = useCallback(
    async (q: PaperQuestion, answerText: string) => {
      const key = paperQuestionKey(q);
      setGradingScoring(gradingRef.current, key);
      patchGrading((m) => setGradingScoring(m, key));
      try {
        const payload = buildEvaluatePayload(
          q,
          answerText,
          sessionIdRef.current,
        );
        const result = await evaluateAnswer(payload);
        patchGrading((m) => setGradingDone(m, key, result));
      } catch (e) {
        const msg = e instanceof Error ? e.message : te("evaluateFailed");
        patchGrading((m) => setGradingError(m, key, msg));
      }
    },
    [patchGrading, te],
  );

  const drainQueue = useCallback(() => {
    while (
      activeRef.current < GRADING_CONCURRENCY &&
      queueRef.current.length > 0
    ) {
      const key = queueRef.current.shift()!;
      const q = questions.find((x) => paperQuestionKey(x) === key);
      const entry = gradingRef.current.get(key);
      if (!q || !entry) continue;
      activeRef.current += 1;
      void runEvaluate(q, entry.answer).finally(() => {
        activeRef.current -= 1;
        drainQueue();
      });
    }
  }, [questions, runEvaluate]);

  const enqueueGrading = useCallback(
    (q: PaperQuestion, answerText: string) => {
      const key = paperQuestionKey(q);
      patchGrading((m) => {
        m.set(key, { status: "pending", answer: answerText });
      });
      queueRef.current.push(key);
      drainQueue();
    },
    [patchGrading, drainQueue],
  );

  const buildQuestions = useCallback(async (): Promise<PaperQuestion[]> => {
    const sid = sessionIdRef.current ?? (await createSession());
    if (sid) {
      sessionIdRef.current = sid;
      setSessionId(sid);
    }
    if (setup.source === "jd") {
      const data = await generatePaperFromJd({
        jd_text: setup.jdText.trim(),
        difficulty: setup.difficulty,
        count: setup.count,
        session_id: sid ?? undefined,
      });
      return data.questions;
    }
    const list: PaperQuestion[] = [];
    for (let i = 0; i < setup.count; i++) {
      if (setup.questionSource === "seed") {
        const data = await generateQuestionSeed({
          topics: setup.topics,
          difficulty: setup.difficulty,
          session_id: sid ?? undefined,
        });
        list.push({
          source: "seed",
          question_id: data.question_id,
          generation_id: null,
          question: data.question,
          topics: data.topics,
          difficulty: data.difficulty,
          expected_key_points: data.expected_key_points,
          reference_snippets: [],
          source_seed_ids: [],
        });
      } else {
        const data = await generateQuestionLlm({
          topics: setup.topics,
          difficulty: setup.difficulty,
          session_id: sid ?? undefined,
        });
        list.push({
          source: "llm",
          question_id: null,
          generation_id: data.generation_id,
          question: data.question,
          topics: data.topics,
          difficulty: data.difficulty,
          expected_key_points: data.expected_key_points,
          reference_snippets: data.reference_snippets,
          source_seed_ids: data.source_seed_ids,
        });
      }
    }
    return list;
  }, [setup]);

  const onStart = useCallback(async () => {
    setError(null);
    setLoading(true);
    try {
      const qs = await buildQuestions();
      if (!qs.length) throw new Error(te("generateFailed"));
      const initAnswers: Record<string, string> = {};
      const initGrading = new Map<string, GradingEntry>();
      qs.forEach((q) => {
        const k = paperQuestionKey(q);
        initAnswers[k] = "";
        initGrading.set(k, createGradingEntry(""));
      });
      setQuestions(qs);
      setAnswers(initAnswers);
      setGrading(initGrading);
      gradingRef.current = initGrading;
      setCurrentIndex(0);
      queueRef.current = [];
      setStep("deck");
    } catch (e) {
      setError(e instanceof Error ? e.message : te("jdBuildFailed"));
    } finally {
      setLoading(false);
    }
  }, [buildQuestions, te]);

  const onNext = useCallback(() => {
    const q = questions[currentIndex];
    if (!q) return;
    const key = paperQuestionKey(q);
    const text = (answers[key] ?? "").trim();
    if (!text) {
      setError(t("emptyAnswer"));
      return;
    }
    setError(null);
    enqueueGrading(q, text);
    if (currentIndex >= questions.length - 1) {
      setStep("summary");
      return;
    }
    setCurrentIndex((i) => i + 1);
  }, [questions, currentIndex, answers, enqueueGrading, t]);

  const onRetry = useCallback(() => {
    setStep("setup");
    setQuestions([]);
    setCurrentIndex(0);
    setAnswers({});
    setGrading(new Map());
    queueRef.current = [];
  }, []);

  const stepLabels = [t("stepSetup"), t("stepDeck"), t("stepSummary")];

  return (
    <div className="space-y-6">
      <div className="flex gap-2 text-xs text-muted-foreground">
        {stepLabels.map((label, i) => {
          const keys: Step[] = ["setup", "deck", "summary"];
          const active = keys[i] === step;
          return (
            <span
              key={label}
              className={
                active ? "font-medium text-primary" : "text-muted-foreground"
              }
            >
              {label}
            </span>
          );
        })}
      </div>

      {loading && (
        <div
          role="status"
          className="flex items-center gap-2 rounded-xl border border-border bg-muted/60 px-4 py-3 text-sm text-dark-muted"
        >
          <Loader2 className="size-4 animate-spin" />
          {setup.source === "jd" ? t("building") : t("generating")}
        </div>
      )}

      {step === "setup" && (
        <div className="-mx-2 px-2 sm:mx-0 sm:px-0">
          <SessionWizard
            topicOptions={topicOptions}
            setup={setup}
            onChange={(patch) => setSetup((s) => ({ ...s, ...patch }))}
            onStart={onStart}
            loading={loading}
            demo={isDemo}
          />
        </div>
      )}

      {step === "deck" && questions.length > 0 && (
        <QuestionDeck
          questions={questions}
          currentIndex={currentIndex}
          answers={answers}
          grading={grading}
          onAnswerChange={(key, text) =>
            setAnswers((a) => ({ ...a, [key]: text }))
          }
          onNext={onNext}
          isLast={currentIndex >= questions.length - 1}
        />
      )}

      {step === "summary" && (
        <SessionSummary
          questions={questions}
          grading={grading}
          onRetry={onRetry}
        />
      )}

      {error && (
        <Card className="border-destructive/50">
          <CardHeader>
            <CardTitle className="text-destructive text-base">
              {tc("errorTitle")}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <pre className="whitespace-pre-wrap text-sm">{error}</pre>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
