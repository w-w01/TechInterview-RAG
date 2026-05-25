"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useLocale, useTranslations } from "next-intl";
import { uiLocaleToApiMode } from "@/lib/locale";
import type { AppLocale } from "@/i18n/routing";
import {
  buildPlanCards,
  matchHighlightedCardIds,
  weakTopicForApi,
  type PlanCard,
} from "@/lib/learn-plan-utils";
import type { TutorPlanResponse, TutorTurn } from "@/lib/types";

export type SyllabusPhase = "config" | "generating" | "timeline";

type TutorRagMeta = {
  original_query: string;
  rewritten_query: string;
  query_type: string;
  retrieval_queries: string[];
  rewrite_changed: boolean;
  rewrite_confidence: number | null;
  retrieval_hits: {
    title: string;
    corpus_id: string;
    doc_id: string;
    source: string;
    lang: string;
    snippet: string;
    score: number;
    fusion_score?: number;
    rerank_score?: number;
    retrieval_query: string;
  }[];
};

type LearnContextValue = {
  locale: AppLocale;
  jdText: string;
  setJdText: (v: string) => void;
  weakTags: string[];
  setWeakTags: (v: string[]) => void;
  planDays: number;
  setPlanDays: (n: number) => void;
  phase: SyllabusPhase;
  learnPlan: TutorPlanResponse | null;
  planCards: PlanCard[];
  loadingPlan: boolean;
  highlightedCardIds: Set<string>;
  pulseCardId: string | null;
  error: string | null;
  setError: (v: string | null) => void;
  generatePlan: () => Promise<void>;
  openEditConfig: () => void;
  onPlanCardClick: (card: PlanCard) => void;
  tutorTurns: TutorTurn[];
  tutorInput: string;
  setTutorInput: (v: string) => void;
  tutorLoading: boolean;
  tutorStreamPriming: boolean;
  tutorFollowups: string[];
  tutorRagMeta: TutorRagMeta | null;
  sendTutorMessage: (message: string) => Promise<void>;
  clearTutorChat: () => void;
  registerTutorContent: (content: string) => void;
};

const LearnContext = createContext<LearnContextValue | null>(null);

function apiBase(): string {
  return process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";
}

export function LearnProvider({ children }: { children: React.ReactNode }) {
  const locale = useLocale() as AppLocale;
  const te = useTranslations("errors");

  const [jdText, setJdText] = useState("");
  const [weakTags, setWeakTags] = useState<string[]>([]);
  const [planDays, setPlanDays] = useState(5);
  const [phase, setPhase] = useState<SyllabusPhase>("config");
  const [learnPlan, setLearnPlan] = useState<TutorPlanResponse | null>(null);
  const [loadingPlan, setLoadingPlan] = useState(false);
  const [highlightedCardIds, setHighlightedCardIds] = useState<Set<string>>(
    new Set(),
  );
  const [pulseCardId, setPulseCardId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);

  const [tutorTurns, setTutorTurns] = useState<TutorTurn[]>([]);
  const [tutorInput, setTutorInput] = useState("");
  const [tutorLoading, setTutorLoading] = useState(false);
  const [tutorStreamPriming, setTutorStreamPriming] = useState(false);
  const [tutorFollowups, setTutorFollowups] = useState<string[]>([]);
  const [tutorRagMeta, setTutorRagMeta] = useState<TutorRagMeta | null>(null);

  const sessionIdRef = useRef<string | null>(null);
  const planCardsRef = useRef<PlanCard[]>([]);
  const highlightTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    sessionIdRef.current = sessionId;
  }, [sessionId]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(`${apiBase()}/sessions`, { method: "POST" });
        if (!res.ok) return;
        const data = (await res.json()) as { session_id: string };
        if (!cancelled && data.session_id) setSessionId(data.session_id);
      } catch {
        /* 无会话仍可继续 */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const ensureSessionId = useCallback(async (): Promise<string | null> => {
    if (sessionIdRef.current) return sessionIdRef.current;
    try {
      const res = await fetch(`${apiBase()}/sessions`, { method: "POST" });
      if (!res.ok) return null;
      const data = (await res.json()) as { session_id: string };
      const sid = data.session_id?.trim();
      if (!sid) return null;
      sessionIdRef.current = sid;
      setSessionId(sid);
      return sid;
    } catch {
      return null;
    }
  }, []);

  const planCards = useMemo(
    () => (learnPlan ? buildPlanCards(learnPlan) : []),
    [learnPlan],
  );

  useEffect(() => {
    planCardsRef.current = planCards;
  }, [planCards]);

  const pushPlanWelcome = useCallback(
    (plan: TutorPlanResponse, days: number) => {
      const day1 = plan.days[0];
      const focus = day1?.focus ?? (locale === "zh" ? "基础巩固" : "fundamentals");
      const content =
        locale === "zh"
          ? `你好！我已经为你量身定制了 ${days} 天的学习计划（已同步在左侧看板）。让我们从 Day 1 的「${focus}」开始聊聊吧……`
          : `Hi! I've built a ${days}-day learning plan for you (see the syllabus on the left). Let's start with Day 1: "${focus}"…`;
      setTutorTurns([
        {
          id: crypto.randomUUID(),
          role: "assistant",
          content,
        },
      ]);
    },
    [locale],
  );

  const registerTutorContent = useCallback((content: string) => {
    const cards = planCardsRef.current;
    if (!cards.length || !content.trim()) return;
    const ids = matchHighlightedCardIds(content, cards);
    if (!ids.length) return;
    setHighlightedCardIds(new Set(ids));
    setPulseCardId(ids[0] ?? null);
    if (highlightTimerRef.current) clearTimeout(highlightTimerRef.current);
    highlightTimerRef.current = setTimeout(() => {
      setPulseCardId(null);
    }, 2800);
  }, []);

  const generatePlan = useCallback(async () => {
    if (jdText.trim().length < 40) {
      setError(te("jdMinLength"));
      return;
    }
    setError(null);
    setPhase("generating");
    setLoadingPlan(true);
    try {
      const sid = await ensureSessionId();
      if (!sid) {
        throw new Error(te("sessionFailed"));
      }
      const res = await fetch(
        `${apiBase()}/sessions/${sid}/tutor/learning-plan`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            jd_text: jdText.trim(),
            weak_topic: weakTopicForApi(weakTags),
            plan_days: planDays,
          }),
        },
      );
      if (!res.ok) {
        const text = await res.text();
        throw new Error(text || res.statusText);
      }
      const data = (await res.json()) as TutorPlanResponse;
      setLearnPlan(data);
      setPhase("timeline");
      setHighlightedCardIds(new Set());
      pushPlanWelcome(data, planDays);
    } catch (e) {
      setLearnPlan(null);
      setPhase("config");
      setError(e instanceof Error ? e.message : te("planFailed"));
    } finally {
      setLoadingPlan(false);
    }
  }, [
    jdText,
    weakTags,
    planDays,
    ensureSessionId,
    te,
    pushPlanWelcome,
  ]);

  const openEditConfig = useCallback(() => {
    setPhase("config");
  }, []);

  const sendTutorMessage = useCallback(
    async (message: string) => {
      const msg = message.trim();
      if (!msg) return;
      setError(null);
      setTutorLoading(true);
      setTutorStreamPriming(true);
      setTutorFollowups([]);
      setTutorRagMeta(null);
      const userId = crypto.randomUUID();
      const assistantId = crypto.randomUUID();
      const historyPayload = tutorTurns.map((t) => ({
        role: t.role,
        content: t.content,
      }));
      setTutorTurns((prev) => [
        ...prev,
        { id: userId, role: "user", content: msg },
        { id: assistantId, role: "assistant", content: "" },
      ]);
      setTutorInput("");

      const rollbackTurns = () => {
        setTutorTurns((prev) => prev.slice(0, -2));
      };

      try {
        const sid = await ensureSessionId();
        if (!sid) {
          rollbackTurns();
          setTutorInput(msg);
          setError(te("sessionFailed"));
          return;
        }
        const res = await fetch(
          `${apiBase()}/sessions/${sid}/tutor/chat/stream`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              jd_text: jdText.trim(),
              weak_topic: weakTopicForApi(weakTags),
              locale_mode: uiLocaleToApiMode(locale),
              use_knowledge_rag: true,
              history: historyPayload,
              user_message: msg,
            }),
          },
        );
        if (!res.ok) {
          const text = await res.text();
          rollbackTurns();
          throw new Error(text || res.statusText);
        }
        const reader = res.body?.getReader();
        if (!reader) {
          rollbackTurns();
          throw new Error(te("streamReadFailed"));
        }
        const decoder = new TextDecoder();
        let buffer = "";
        let acc = "";
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          for (;;) {
            const sep = buffer.indexOf("\n\n");
            if (sep < 0) break;
            const frame = buffer.slice(0, sep);
            buffer = buffer.slice(sep + 2);
            if (!frame.startsWith("data: ")) continue;
            let payload: {
              type?: string;
              text?: string;
              message?: string;
              suggested_followups?: string[];
              original_query?: string;
              rewritten_query?: string;
              query_type?: string;
              retrieval_queries?: string[];
              rewrite_changed?: boolean;
              rewrite_confidence?: number | null;
              retrieval_hits?: TutorRagMeta["retrieval_hits"];
            };
            try {
              payload = JSON.parse(frame.slice(6)) as typeof payload;
            } catch {
              continue;
            }
            const ev = payload.type;
            if (ev === "meta") {
              if (
                typeof payload.original_query === "string" &&
                typeof payload.rewritten_query === "string" &&
                Array.isArray(payload.retrieval_hits)
              ) {
                setTutorRagMeta({
                  original_query: payload.original_query,
                  rewritten_query: payload.rewritten_query,
                  query_type: String(payload.query_type ?? ""),
                  retrieval_queries: (payload.retrieval_queries ?? []).map(
                    String,
                  ),
                  rewrite_changed: Boolean(payload.rewrite_changed),
                  rewrite_confidence:
                    typeof payload.rewrite_confidence === "number"
                      ? payload.rewrite_confidence
                      : null,
                  retrieval_hits: payload.retrieval_hits,
                });
              }
            } else if (ev === "delta" && typeof payload.text === "string") {
              setTutorStreamPriming(false);
              acc += payload.text;
              registerTutorContent(acc);
              setTutorTurns((prev) => {
                const next = [...prev];
                const last = next[next.length - 1];
                if (last?.role === "assistant") {
                  next[next.length - 1] = {
                    ...last,
                    content: last.content + payload.text,
                  };
                }
                return next;
              });
            } else if (ev === "done") {
              setTutorFollowups(
                Array.isArray(payload.suggested_followups)
                  ? payload.suggested_followups
                  : [],
              );
            } else if (ev === "error") {
              rollbackTurns();
              throw new Error(payload.message || "Tutor stream failed");
            }
          }
        }
      } catch (e) {
        setError(e instanceof Error ? e.message : te("streamReadFailed"));
      } finally {
        setTutorLoading(false);
        setTutorStreamPriming(false);
      }
    },
    [
      tutorTurns,
      ensureSessionId,
      jdText,
      weakTags,
      locale,
      te,
      registerTutorContent,
    ],
  );

  const onPlanCardClick = useCallback(
    (card: PlanCard) => {
      const template =
        locale === "zh"
          ? `我想详细了解一下 Day ${card.day} 计划中的「${card.label}」`
          : `I'd like to learn more about "${card.label}" in Day ${card.day} of my plan.`;
      setHighlightedCardIds(new Set([card.id]));
      setPulseCardId(card.id);
      void sendTutorMessage(template);
    },
    [locale, sendTutorMessage],
  );

  const clearTutorChat = useCallback(() => {
    setTutorTurns([]);
    setTutorFollowups([]);
    setTutorRagMeta(null);
    setTutorInput("");
  }, []);

  const value: LearnContextValue = {
    locale,
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
    error,
    setError,
    generatePlan,
    openEditConfig,
    onPlanCardClick,
    tutorTurns,
    tutorInput,
    setTutorInput,
    tutorLoading,
    tutorStreamPriming,
    tutorFollowups,
    tutorRagMeta,
    sendTutorMessage,
    clearTutorChat,
    registerTutorContent,
  };

  return (
    <LearnContext.Provider value={value}>
      <div className="flex h-full min-h-0 flex-col">{children}</div>
    </LearnContext.Provider>
  );
}

export function useLearn() {
  const ctx = useContext(LearnContext);
  if (!ctx) throw new Error("useLearn must be used within LearnProvider");
  return ctx;
}
