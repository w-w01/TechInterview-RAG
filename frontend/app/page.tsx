"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { Textarea } from "@/components/ui/textarea";
import { Loader2 } from "lucide-react";
import { TutorMarkdown } from "@/components/tutor-markdown";

const DIFFICULTIES = ["beginner", "intermediate", "advanced"] as const;

type Difficulty = (typeof DIFFICULTIES)[number];

type TopicOption = { slug: string; label: string };

type ReferenceSnippet = { source: string; content: string };

type GenerateResponse = {
  question_id: string;
  question: string;
  topics: string[];
  difficulty: string;
  expected_key_points: string[];
};

type GenerateLlmResponse = {
  generation_id: string;
  question: string;
  topics: string[];
  difficulty: string;
  expected_key_points: string[];
  reference_snippets: ReferenceSnippet[];
  source_seed_ids: string[];
};

type PaperQuestion = {
  source: "seed" | "llm";
  question_id?: string | null;
  generation_id?: string | null;
  question: string;
  topics: string[];
  difficulty: string;
  expected_key_points: string[];
  reference_snippets: ReferenceSnippet[];
  source_seed_ids: string[];
};

type PaperBuildMeta = {
  seed_count: number;
  ai_count: number;
  ai_ratio: number;
  ai_ratio_boosted: boolean;
  ai_ratio_reason: "normal_base_ratio" | "high_seen_ratio" | "seed_shortage";
  seen_ratio_in_candidates: number;
  unseen_candidate_count: number;
  weak_topics_used: string[];
  topic_priority: string[];
  baseline_window: number;
  topic_level_plan: Record<string, string>;
  adjustment_reasons: string[];
  jd_plan_mode?: string;
  planner_notes?: string[];
  selector_notes?: string;
  selector_candidate_count?: number;
  program_fixes?: string[];
};

type QuestionBundle =
  | { mode: "seed"; data: GenerateResponse }
  | { mode: "llm"; data: GenerateLlmResponse };

type QuestionSource = "seed" | "llm";

type EvaluateResponse = {
  score: number;
  strengths: string[];
  missing_points: string[];
  improved_answer: string;
  weak_topics: string[];
  study_topics?: string[];
  reference_evidence: ReferenceSnippet[];
};

type TutorPlanResponse = {
  plan_title: string;
  jd_priority_guess_markdown: string;
  days: {
    day: number;
    focus: string;
    tasks: { task: string; estimated_minutes: number }[];
  }[];
  tips: string[];
};

type TutorTurn = { id: string; role: string; content: string };

type QuestionDraftState = {
  answer: string;
  evaluation: EvaluateResponse | null;
};

function apiBase(): string {
  return process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";
}

export default function Home() {
  const [topicOptions, setTopicOptions] = useState<TopicOption[]>([]);
  // 默认 slug 须存在于题库白名单；与 seeds 中 general_programming 一致（首轮 GET /topics 后会再次校正）
  const [selectedTopics, setSelectedTopics] = useState<string[]>([
    "general_programming",
  ]);
  /** 最近一次「生成题目」成功时使用的筛选标签，评卷时必须一致以防交集校验失败 */
  const [sessionTopics, setSessionTopics] = useState<string[]>([]);
  const [difficulty, setDifficulty] = useState<Difficulty>("intermediate");
  const [questionSource, setQuestionSource] = useState<QuestionSource>("seed");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [questionBundle, setQuestionBundle] = useState<QuestionBundle | null>(
    null,
  );
  const [answer, setAnswer] = useState("");
  const [evaluation, setEvaluation] = useState<EvaluateResponse | null>(null);
  const [loadingGen, setLoadingGen] = useState(false);
  const [loadingEval, setLoadingEval] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [evidenceOpen, setEvidenceOpen] = useState(true);

  const [mainTab, setMainTab] = useState<"practice" | "learn">("practice");
  const [learnWeakTopic, setLearnWeakTopic] = useState("");
  const [planDays, setPlanDays] = useState(5);
  const [learnPlan, setLearnPlan] = useState<TutorPlanResponse | null>(null);
  const [loadingPlan, setLoadingPlan] = useState(false);
  const [tutorTurns, setTutorTurns] = useState<TutorTurn[]>([]);
  const [tutorInput, setTutorInput] = useState("");
  const [tutorLoading, setTutorLoading] = useState(false);
  /** 首条 delta 前为 true，用于顶栏「正在回复」与占位，避免与流式气泡重复 */
  const [tutorStreamPriming, setTutorStreamPriming] = useState(false);
  const [tutorFollowups, setTutorFollowups] = useState<string[]>([]);
  const [learnQuizTopics, setLearnQuizTopics] = useState<string[]>([
    "general_programming",
  ]);
  const [learnQuizBundle, setLearnQuizBundle] = useState<QuestionBundle | null>(
    null,
  );
  const [learnQuizAnswer, setLearnQuizAnswer] = useState("");
  const [learnQuizEval, setLearnQuizEval] = useState<EvaluateResponse | null>(
    null,
  );
  const [learnQuizSessionTopics, setLearnQuizSessionTopics] = useState<string[]>(
    [],
  );
  const [loadingLearnQuizGen, setLoadingLearnQuizGen] = useState(false);
  const [loadingLearnQuizEval, setLoadingLearnQuizEval] = useState(false);

  /** JD 向量组卷 */
  const [jdText, setJdText] = useState("");
  const [jdPaperCount, setJdPaperCount] = useState(5);
  const [jdPaper, setJdPaper] = useState<PaperQuestion[] | null>(null);
  const [jdPaperMeta, setJdPaperMeta] = useState<PaperBuildMeta | null>(null);
  const [loadingJd, setLoadingJd] = useState(false);
  const [jdExpandedKey, setJdExpandedKey] = useState<string | null>(null);
  const [jdDrafts, setJdDrafts] = useState<Record<string, QuestionDraftState>>(
    {},
  );
  const [jdEvaluatingKey, setJdEvaluatingKey] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(`${apiBase()}/topics`);
        if (!res.ok) return;
        const data = (await res.json()) as { topics: TopicOption[] };
        if (cancelled || !data.topics?.length) return;
        setTopicOptions(data.topics);
        setSelectedTopics((prev) => {
          const valid = prev.filter((s) =>
            data.topics.some((t) => t.slug === s),
          );
          return valid.length ? valid : [data.topics[0].slug];
        });
        setLearnQuizTopics((prev) => {
          const valid = prev.filter((s) =>
            data.topics.some((t) => t.slug === s),
          );
          return valid.length ? valid : [data.topics[0].slug];
        });
      } catch {
        /* 忽略，保留默认 java */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(`${apiBase()}/sessions`, { method: "POST" });
        if (!res.ok) return;
        const data = (await res.json()) as { session_id: string };
        if (!cancelled && data.session_id) setSessionId(data.session_id);
      } catch {
        /* 无会话仍可出题，仅不记录历史 */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  /** 与 state 同步，避免连续点击时在 setState 生效前重复创建会话 */
  const sessionIdRef = useRef<string | null>(null);
  useEffect(() => {
    sessionIdRef.current = sessionId;
  }, [sessionId]);

  /** 页面加载时 /sessions 可能失败（后端未起、API 地址错误）；在首次需要会话时再试一次 */
  const ensureSessionId = useCallback(async (): Promise<string | null> => {
    if (sessionIdRef.current) {
      return sessionIdRef.current;
    }
    try {
      const res = await fetch(`${apiBase()}/sessions`, { method: "POST" });
      if (!res.ok) {
        return null;
      }
      const data = (await res.json()) as { session_id: string };
      const sid = data.session_id?.trim();
      if (!sid) {
        return null;
      }
      sessionIdRef.current = sid;
      setSessionId(sid);
      return sid;
    } catch {
      return null;
    }
  }, []);

  const labelForSlug = useCallback(
    (slug: string) =>
      topicOptions.find((t) => t.slug === slug)?.label ?? slug,
    [topicOptions],
  );

  const toggleTopic = useCallback((slug: string) => {
    setSelectedTopics((prev) => {
      if (prev.includes(slug)) {
        const next = prev.filter((s) => s !== slug);
        return next.length ? next : prev;
      }
      return [...prev, slug];
    });
  }, []);

  const toggleLearnQuizTopic = useCallback((slug: string) => {
    setLearnQuizTopics((prev) => {
      if (prev.includes(slug)) {
        const next = prev.filter((s) => s !== slug);
        return next.length ? next : prev;
      }
      return [...prev, slug];
    });
  }, []);

  const paperQuestionKey = useCallback((q: PaperQuestion) => {
    if (q.source === "seed") return `seed:${q.question_id ?? ""}`;
    return `llm:${q.generation_id ?? ""}`;
  }, []);

  const onGenerate = useCallback(async () => {
    setError(null);
    setEvaluation(null);
    setLoadingGen(true);
    try {
      if (questionSource === "seed") {
        const res = await fetch(`${apiBase()}/generate-question`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            topics: selectedTopics,
            difficulty,
            ...(sessionId ? { session_id: sessionId } : {}),
          }),
        });
        if (!res.ok) {
          const text = await res.text();
          throw new Error(text || res.statusText);
        }
        const data = (await res.json()) as GenerateResponse;
        setQuestionBundle({ mode: "seed", data });
      } else {
        const res = await fetch(`${apiBase()}/generate-question-llm`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            topics: selectedTopics,
            difficulty,
            reference_max: 5,
            ...(sessionId ? { session_id: sessionId } : {}),
          }),
        });
        if (!res.ok) {
          const text = await res.text();
          throw new Error(text || res.statusText);
        }
        const data = (await res.json()) as GenerateLlmResponse;
        setQuestionBundle({ mode: "llm", data });
      }
      setSessionTopics([...selectedTopics]);
      setAnswer("");
    } catch (e) {
      setQuestionBundle(null);
      setSessionTopics([]);
      setError(e instanceof Error ? e.message : "Generate failed");
    } finally {
      setLoadingGen(false);
    }
  }, [selectedTopics, difficulty, questionSource, sessionId]);

  const onBuildPaperFromJd = useCallback(async () => {
    setError(null);
    setLoadingJd(true);
    try {
      const res = await fetch(`${apiBase()}/generate-paper-from-jd`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          jd_text: jdText.trim(),
          difficulty,
          count: jdPaperCount,
          ...(sessionId ? { session_id: sessionId } : {}),
        }),
      });
      if (!res.ok) {
        const text = await res.text();
        throw new Error(text || res.statusText);
      }
      const data = (await res.json()) as {
        questions: PaperQuestion[];
        meta: PaperBuildMeta;
      };
      setJdPaper(data.questions);
      setJdPaperMeta(data.meta);
      const initDrafts: Record<string, QuestionDraftState> = {};
      data.questions.forEach((q) => {
        initDrafts[paperQuestionKey(q)] = { answer: "", evaluation: null };
      });
      setJdDrafts(initDrafts);
      setJdExpandedKey(
        data.questions.length > 0 ? paperQuestionKey(data.questions[0]) : null,
      );
    } catch (e) {
      setJdPaper(null);
      setJdPaperMeta(null);
      setJdDrafts({});
      setJdExpandedKey(null);
      setError(e instanceof Error ? e.message : "JD 组卷失败");
    } finally {
      setLoadingJd(false);
    }
  }, [jdText, difficulty, jdPaperCount, sessionId, paperQuestionKey]);

  const updateJdDraftAnswer = useCallback(
    (q: PaperQuestion, next: string) => {
      const key = paperQuestionKey(q);
      setJdDrafts((prev) => ({
        ...prev,
        [key]: {
          answer: next,
          evaluation: prev[key]?.evaluation ?? null,
        },
      }));
    },
    [paperQuestionKey],
  );

  const evaluateJdQuestion = useCallback(
    async (q: PaperQuestion) => {
      const key = paperQuestionKey(q);
      const draft = jdDrafts[key];
      const answerText = (draft?.answer ?? "").trim();
      if (!answerText) {
        setError("请先填写该题答案。");
        return;
      }
      setError(null);
      setJdEvaluatingKey(key);
      try {
        const base = {
          question: q.question,
          student_answer: answerText,
          topics: q.topics,
          difficulty: q.difficulty,
          ...(sessionId ? { session_id: sessionId } : {}),
        };
        const payload =
          q.source === "seed"
            ? { ...base, question_id: q.question_id }
            : { ...base, generation_id: q.generation_id };
        const res = await fetch(`${apiBase()}/evaluate-answer`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        if (!res.ok) {
          const text = await res.text();
          throw new Error(text || res.statusText);
        }
        const data = (await res.json()) as EvaluateResponse;
        setJdDrafts((prev) => ({
          ...prev,
          [key]: {
            answer: prev[key]?.answer ?? "",
            evaluation: data,
          },
        }));
      } catch (e) {
        setError(e instanceof Error ? e.message : "评估失败");
      } finally {
        setJdEvaluatingKey(null);
      }
    },
    [jdDrafts, paperQuestionKey, sessionId],
  );

  const onEvaluate = useCallback(async () => {
    if (!questionBundle) {
      setError("请先生成题目。");
      return;
    }
    if (!answer.trim()) {
      setError("请先填写你的答案。");
      return;
    }
    if (sessionTopics.length === 0) {
      setError("评卷缺少出题时的标签上下文，请重新生成题目。");
      return;
    }
    setError(null);
    setLoadingEval(true);
    try {
      const base = {
        question: questionBundle.data.question,
        student_answer: answer,
        topics: sessionTopics,
        difficulty: questionBundle.data.difficulty,
        ...(sessionId ? { session_id: sessionId } : {}),
      };
      const payload =
        questionBundle.mode === "seed"
          ? { ...base, question_id: questionBundle.data.question_id }
          : { ...base, generation_id: questionBundle.data.generation_id };
      const res = await fetch(`${apiBase()}/evaluate-answer`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        const text = await res.text();
        throw new Error(text || res.statusText);
      }
      const data = (await res.json()) as EvaluateResponse;
      setEvaluation(data);
      setEvidenceOpen(true);
    } catch (e) {
      setEvaluation(null);
      setError(e instanceof Error ? e.message : "Evaluate failed");
    } finally {
      setLoadingEval(false);
    }
  }, [answer, questionBundle, sessionTopics, sessionId]);

  const onGenerateLearnQuiz = useCallback(async () => {
    setError(null);
    setLearnQuizEval(null);
    setLoadingLearnQuizGen(true);
    try {
      const sid = await ensureSessionId();
      if (!sid) {
        throw new Error(
          "无法创建练习会话，请确认后端已启动（默认 http://127.0.0.1:8000）与 NEXT_PUBLIC_API_URL。",
        );
      }
      const res = await fetch(`${apiBase()}/generate-question-llm`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          topics: learnQuizTopics,
          difficulty,
          reference_max: 5,
          session_id: sid,
        }),
      });
      if (!res.ok) {
        const text = await res.text();
        throw new Error(text || res.statusText);
      }
      const data = (await res.json()) as GenerateLlmResponse;
      setLearnQuizBundle({ mode: "llm", data });
      setLearnQuizSessionTopics([...learnQuizTopics]);
      setLearnQuizAnswer("");
    } catch (e) {
      setLearnQuizBundle(null);
      setLearnQuizSessionTopics([]);
      setError(e instanceof Error ? e.message : "小测出题失败");
    } finally {
      setLoadingLearnQuizGen(false);
    }
  }, [learnQuizTopics, difficulty, ensureSessionId]);

  const onEvaluateLearnQuiz = useCallback(async () => {
    if (!learnQuizBundle || learnQuizBundle.mode !== "llm") {
      setError("请先生成小测题目。");
      return;
    }
    if (!learnQuizAnswer.trim()) {
      setError("请填写小测答案。");
      return;
    }
    if (learnQuizSessionTopics.length === 0) {
      setError("小测缺少标签上下文，请重新出题。");
      return;
    }
    setError(null);
    setLoadingLearnQuizEval(true);
    try {
      const sid = await ensureSessionId();
      if (!sid) {
        throw new Error(
          "无法创建练习会话，请确认后端已启动与 NEXT_PUBLIC_API_URL。",
        );
      }
      const res = await fetch(`${apiBase()}/evaluate-answer`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question: learnQuizBundle.data.question,
          student_answer: learnQuizAnswer,
          topics: learnQuizSessionTopics,
          difficulty: learnQuizBundle.data.difficulty,
          generation_id: learnQuizBundle.data.generation_id,
          session_id: sid,
        }),
      });
      if (!res.ok) {
        const text = await res.text();
        throw new Error(text || res.statusText);
      }
      const data = (await res.json()) as EvaluateResponse;
      setLearnQuizEval(data);
    } catch (e) {
      setLearnQuizEval(null);
      setError(e instanceof Error ? e.message : "小测评卷失败");
    } finally {
      setLoadingLearnQuizEval(false);
    }
  }, [
    learnQuizAnswer,
    learnQuizBundle,
    learnQuizSessionTopics,
    ensureSessionId,
  ]);

  const onTutorPlan = useCallback(async () => {
    if (jdText.trim().length < 40) {
      setError("学习计划需要 JD 不少于约 40 字。");
      return;
    }
    setError(null);
    setLoadingPlan(true);
    try {
      const sid = await ensureSessionId();
      if (!sid) {
        throw new Error(
          "无法创建练习会话，请确认后端已启动（默认 http://127.0.0.1:8000）与 NEXT_PUBLIC_API_URL。",
        );
      }
      const res = await fetch(
        `${apiBase()}/sessions/${sid}/tutor/learning-plan`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            jd_text: jdText.trim(),
            weak_topic: learnWeakTopic.trim(),
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
    } catch (e) {
      setLearnPlan(null);
      setError(e instanceof Error ? e.message : "学习计划生成失败");
    } finally {
      setLoadingPlan(false);
    }
  }, [ensureSessionId, jdText, learnWeakTopic, planDays]);

  const onTutorSend = useCallback(async () => {
    const msg = tutorInput.trim();
    if (!msg) return;
    setError(null);
    setTutorLoading(true);
    setTutorStreamPriming(true);
    setTutorFollowups([]);
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
        setError(
          "无法创建练习会话，请确认后端已启动（默认 http://127.0.0.1:8000）与 NEXT_PUBLIC_API_URL。",
        );
        setTutorLoading(false);
        setTutorStreamPriming(false);
        return;
      }
      const res = await fetch(
        `${apiBase()}/sessions/${sid}/tutor/chat/stream`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            jd_text: jdText.trim(),
            weak_topic: learnWeakTopic.trim(),
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
        throw new Error("无法读取响应流");
      }
      const decoder = new TextDecoder();
      let buffer = "";
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
          let payload: { type?: string; text?: string; message?: string; suggested_followups?: string[] };
          try {
            payload = JSON.parse(frame.slice(6)) as typeof payload;
          } catch {
            continue;
          }
          const ev = payload.type;
          if (ev === "delta" && typeof payload.text === "string") {
            setTutorStreamPriming(false);
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
            throw new Error(payload.message || "Tutor 流式输出失败");
          }
        }
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Tutor 对话失败");
    } finally {
      setTutorLoading(false);
      setTutorStreamPriming(false);
    }
  }, [ensureSessionId, jdText, learnWeakTopic, tutorInput, tutorTurns]);

  const selectClass =
    "flex h-10 w-full max-w-md rounded-md border border-input bg-background px-3 py-2 text-sm shadow-xs outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50";

  const practiceLoadingLabel = loadingJd
    ? "正在根据 JD 组卷，请稍候…"
    : loadingGen
      ? "正在生成题目…"
      : loadingEval
        ? "正在评卷…"
        : jdEvaluatingKey
          ? "正在评估试卷中的题目…"
          : null;

  const learnLoadingLabel = loadingPlan
    ? "正在推断 JD 侧重点并生成学习计划…"
    : tutorStreamPriming
      ? "Tutor 正在回复…"
      : loadingLearnQuizGen
        ? "正在生成小测题…"
        : loadingLearnQuizEval
          ? "正在评卷…"
          : null;

  return (
    <div className="min-h-screen bg-muted/40 px-4 py-10">
      <div className="mx-auto flex w-full max-w-3xl flex-col gap-8">
        <header className="space-y-3">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
            <div className="space-y-1">
              <h1 className="text-2xl font-semibold tracking-tight">
                InterviewMate RAG
              </h1>
              <p className="text-sm text-muted-foreground">
                本地演示：可按标签随机/AI 出题，或粘贴 JD
                做向量检索组卷后选题练习；评卷均为 LLM rubric；「学习」页提供基于 JD
                的学习计划（含侧重点推断）与 Tutor 对话。页面加载时会创建后端练习会话。
              </p>
            </div>
            <div className="flex shrink-0 gap-2">
              <Button
                type="button"
                size="sm"
                variant={mainTab === "practice" ? "default" : "outline"}
                onClick={() => setMainTab("practice")}
              >
                答题
              </Button>
              <Button
                type="button"
                size="sm"
                variant={mainTab === "learn" ? "default" : "outline"}
                onClick={() => setMainTab("learn")}
              >
                学习
              </Button>
            </div>
          </div>
        </header>

        {mainTab === "practice" && (
          <>
        {practiceLoadingLabel && (
          <div
            role="status"
            className="flex items-center gap-2 rounded-lg border border-border bg-muted/50 px-4 py-3 text-sm text-muted-foreground"
          >
            <Loader2 className="size-4 shrink-0 animate-spin" aria-hidden />
            <span>{practiceLoadingLabel}</span>
          </div>
        )}
        <Card>
          <CardHeader>
            <CardTitle>JD 组卷（向量检索）</CardTitle>
            <CardDescription>
              粘贴职位描述纯文本（不少于约 40
              字）；使用下方「难度」与题目数量，从题库中检索最相关的真题列表。点击某一题开始作答（评卷时请保持使用本题自带标签，勿改勾选）。
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            <div className="flex flex-col gap-2">
              <Label htmlFor="jd-text">职位描述（JD）</Label>
              <Textarea
                id="jd-text"
                rows={6}
                value={jdText}
                onChange={(e) => setJdText(e.target.value)}
                placeholder="粘贴 JD 全文或核心要求……"
                className="resize-y"
              />
            </div>
            <div className="flex flex-col gap-4 sm:flex-row sm:flex-wrap sm:items-end">
              <div className="flex flex-col gap-2">
                <Label htmlFor="jd-count">题目数量</Label>
                <input
                  id="jd-count"
                  type="number"
                  min={1}
                  max={20}
                  className={selectClass}
                  value={jdPaperCount}
                  onChange={(e) =>
                    setJdPaperCount(
                      Math.min(
                        20,
                        Math.max(1, parseInt(e.target.value, 10) || 1),
                      ),
                    )
                  }
                />
              </div>
              <Button
                type="button"
                variant="secondary"
                onClick={onBuildPaperFromJd}
                disabled={loadingJd || jdText.trim().length < 40}
              >
                {loadingJd ? "组卷中…" : "根据 JD 组卷"}
              </Button>
            </div>
            {jdPaperMeta && (
              <div className="rounded-md border border-border bg-muted/40 p-3 text-xs text-muted-foreground">
                <p>
                  组卷说明：真题 {jdPaperMeta.seed_count} 题，AI {jdPaperMeta.ai_count} 题，
                  AI 占比 {(jdPaperMeta.ai_ratio * 100).toFixed(1)}%。
                  {jdPaperMeta.ai_ratio_boosted
                    ? ` 已触发比例提升（${jdPaperMeta.ai_ratio_reason}）。`
                    : " 使用基础比例（真题优先）。"}
                </p>
                <p className="mt-1">
                  候选去重后未做真题数：{jdPaperMeta.unseen_candidate_count}，
                  候选已做占比：{(jdPaperMeta.seen_ratio_in_candidates * 100).toFixed(1)}%。
                </p>
                {jdPaperMeta.weak_topics_used.length > 0 && (
                  <p className="mt-1">
                    本轮补弱参考：{jdPaperMeta.weak_topics_used.join("、")}
                  </p>
                )}
                {jdPaperMeta.topic_priority?.length > 0 && (
                  <p className="mt-1">
                    JD考点优先级：{jdPaperMeta.topic_priority.join(" > ")}
                  </p>
                )}
                {Object.keys(jdPaperMeta.topic_level_plan ?? {}).length > 0 && (
                  <p className="mt-1">
                    自适应窗口：最近 {jdPaperMeta.baseline_window} 卷；
                    难度计划：
                    {Object.entries(jdPaperMeta.topic_level_plan)
                      .map(([k, v]) => `${k}:${v}`)
                      .join("，")}
                  </p>
                )}
                {jdPaperMeta.adjustment_reasons?.length > 0 && (
                  <p className="mt-1">
                    调整依据：{jdPaperMeta.adjustment_reasons.join("；")}
                  </p>
                )}
                {jdPaperMeta.selector_candidate_count != null &&
                  jdPaperMeta.selector_candidate_count > 0 && (
                    <p className="mt-1">
                      送入选题模型的候选真题：{jdPaperMeta.selector_candidate_count} 道（仅允许从中选
                      id）。
                    </p>
                  )}
                {jdPaperMeta.planner_notes && jdPaperMeta.planner_notes.length > 0 && (
                  <p className="mt-1">
                    Planner：{jdPaperMeta.planner_notes.join("；")}
                  </p>
                )}
                {jdPaperMeta.selector_notes && jdPaperMeta.selector_notes.trim() !== "" && (
                  <p className="mt-1">Selector：{jdPaperMeta.selector_notes}</p>
                )}
                {jdPaperMeta.program_fixes && jdPaperMeta.program_fixes.length > 0 && (
                  <p className="mt-1">
                    程序校验：{jdPaperMeta.program_fixes.join("；")}
                  </p>
                )}
              </div>
            )}
            {jdPaper && jdPaper.length > 0 && (
              <div className="flex flex-col gap-2">
                <Label>检索到的题目（点击一题开始练习）</Label>
                <ul className="flex flex-col gap-2">
                  {jdPaper.map((q, idx) => (
                    <li key={`${q.source}-${q.question_id ?? q.generation_id ?? idx}`}>
                      <div className="rounded-md border border-border bg-card px-3 py-3 text-sm">
                        <div className="flex items-center justify-between gap-3">
                          <div>
                            <p className="font-medium text-muted-foreground">
                              {q.source === "seed"
                                ? `真题 ${q.question_id ?? ""}`
                                : `AI ${q.generation_id ?? ""}`}
                            </p>
                            <p className="mt-1 line-clamp-2">{q.question}</p>
                          </div>
                          <Button
                            type="button"
                            size="sm"
                            variant="outline"
                            onClick={() =>
                              setJdExpandedKey((prev) =>
                                prev === paperQuestionKey(q)
                                  ? null
                                  : paperQuestionKey(q),
                              )
                            }
                          >
                            {jdExpandedKey === paperQuestionKey(q)
                              ? "收起"
                              : "展开作答"}
                          </Button>
                        </div>
                        {jdExpandedKey === paperQuestionKey(q) && (
                          <div className="mt-3 space-y-3 border-t pt-3">
                            <Textarea
                              rows={6}
                              value={jdDrafts[paperQuestionKey(q)]?.answer ?? ""}
                              onChange={(e) =>
                                updateJdDraftAnswer(q, e.target.value)
                              }
                              placeholder="在此输入该题答案..."
                            />
                            <div className="flex gap-2">
                              <Button
                                type="button"
                                onClick={() => evaluateJdQuestion(q)}
                                disabled={jdEvaluatingKey === paperQuestionKey(q)}
                              >
                                {jdEvaluatingKey === paperQuestionKey(q)
                                  ? "评估中..."
                                  : "评估该题"}
                              </Button>
                            </div>
                            {jdDrafts[paperQuestionKey(q)]?.evaluation && (
                              <div className="space-y-3 rounded-md border bg-muted/30 p-3">
                                <p className="text-sm">
                                  分数：{" "}
                                  <span className="font-semibold">
                                    {jdDrafts[paperQuestionKey(q)]?.evaluation?.score}
                                  </span>
                                  /10
                                </p>
                                <div>
                                  <p className="text-xs font-medium">亮点</p>
                                  <ul className="list-disc pl-5 text-xs">
                                    {jdDrafts[
                                      paperQuestionKey(q)
                                    ]?.evaluation?.strengths.map((s) => (
                                      <li key={s}>{s}</li>
                                    ))}
                                  </ul>
                                </div>
                                <div>
                                  <p className="text-xs font-medium">不足</p>
                                  <ul className="list-disc pl-5 text-xs">
                                    {jdDrafts[
                                      paperQuestionKey(q)
                                    ]?.evaluation?.missing_points.map((s) => (
                                      <li key={s}>{s}</li>
                                    ))}
                                  </ul>
                                </div>
                                <div>
                                  <p className="text-xs font-medium">改进版回答</p>
                                  <p className="whitespace-pre-wrap text-xs leading-relaxed">
                                    {
                                      jdDrafts[paperQuestionKey(q)]?.evaluation
                                        ?.improved_answer
                                    }
                                  </p>
                                </div>
                                {jdDrafts[
                                  paperQuestionKey(q)
                                ]?.evaluation?.weak_topics.length ? (
                                  <div>
                                    <p className="text-xs font-medium">
                                      薄弱知识点
                                    </p>
                                    <ul className="list-disc pl-5 text-xs">
                                      {jdDrafts[
                                        paperQuestionKey(q)
                                      ]?.evaluation?.weak_topics.map((w) => (
                                        <li key={w}>{w}</li>
                                      ))}
                                    </ul>
                                  </div>
                                ) : null}
                                {(jdDrafts[paperQuestionKey(q)]?.evaluation
                                  ?.study_topics?.length ?? 0) > 0 ? (
                                  <div>
                                    <p className="text-xs font-medium">
                                      建议学习方向
                                    </p>
                                    <ul className="list-disc pl-5 text-xs">
                                      {(
                                        jdDrafts[paperQuestionKey(q)]?.evaluation
                                          ?.study_topics ?? []
                                      ).map((s) => (
                                        <li key={s}>{s}</li>
                                      ))}
                                    </ul>
                                  </div>
                                ) : null}
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>练习设置</CardTitle>
            <CardDescription>
              勾选至少一个主题标签与难度；出题来源选「真题」则从池中随机抽种子题，选「AI
              生成」则在同池抽样少样本后由模型命制新题（池空时为零样本）。
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            <div className="flex flex-col gap-2">
              <Label>出题来源</Label>
              <div className="flex flex-wrap gap-6">
                <label className="flex cursor-pointer items-center gap-2 text-sm">
                  <input
                    type="radio"
                    name="questionSource"
                    className="size-4 border-input"
                    checked={questionSource === "seed"}
                    onChange={() => setQuestionSource("seed")}
                  />
                  <span>真题（题库随机）</span>
                </label>
                <label className="flex cursor-pointer items-center gap-2 text-sm">
                  <input
                    type="radio"
                    name="questionSource"
                    className="size-4 border-input"
                    checked={questionSource === "llm"}
                    onChange={() => setQuestionSource("llm")}
                  />
                  <span>AI 生成</span>
                </label>
              </div>
            </div>
            <div className="flex flex-col gap-2">
              <Label>主题标签（多选）</Label>
              <div className="flex flex-wrap gap-3">
                {topicOptions.map((opt) => (
                  <label
                    key={opt.slug}
                    className="flex cursor-pointer items-center gap-2 text-sm"
                  >
                    <input
                      type="checkbox"
                      className="size-4 rounded border-input"
                      checked={selectedTopics.includes(opt.slug)}
                      onChange={() => toggleTopic(opt.slug)}
                    />
                    <span>{opt.label}</span>
                  </label>
                ))}
              </div>
            </div>
            <div className="flex flex-col gap-4 sm:flex-row sm:flex-wrap sm:items-end">
              <div className="flex flex-col gap-2">
                <Label htmlFor="difficulty">难度</Label>
                <select
                  id="difficulty"
                  className={selectClass}
                  value={difficulty}
                  onChange={(e) =>
                    setDifficulty(e.target.value as Difficulty)
                  }
                >
                  {DIFFICULTIES.map((d) => (
                    <option key={d} value={d}>
                      {d}
                    </option>
                  ))}
                </select>
              </div>
              <Button
                type="button"
                onClick={onGenerate}
                disabled={loadingGen || selectedTopics.length === 0}
                className="sm:ml-2"
              >
                {loadingGen ? "生成中..." : "生成题目"}
              </Button>
            </div>
          </CardContent>
        </Card>

        {questionBundle && (
          <>
            <Card>
              <CardHeader>
                <CardTitle>面试题</CardTitle>
                <CardDescription>
                  {questionBundle.data.topics.map(labelForSlug).join(" · ")} /{" "}
                  {questionBundle.data.difficulty} /{" "}
                  {questionBundle.mode === "seed"
                    ? `真题 id: ${questionBundle.data.question_id}`
                    : `AI 题 generation_id: ${questionBundle.data.generation_id}`}
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <p className="text-sm leading-relaxed">
                  {questionBundle.data.question}
                </p>
                {questionBundle.mode === "llm" &&
                  questionBundle.data.reference_snippets.length > 0 && (
                    <details className="rounded-lg border border-border bg-card/30 text-sm">
                      <summary className="cursor-pointer px-3 py-2 font-medium">
                        本题 AI 参考的种子片段（可选阅读）
                      </summary>
                      <div className="space-y-2 border-t px-3 py-2 text-muted-foreground">
                        {questionBundle.data.reference_snippets.map((s, i) => (
                          <div key={`ref-${i}`}>
                            <p className="text-xs">{s.source}</p>
                            <pre className="mt-1 whitespace-pre-wrap rounded bg-muted/50 p-2 text-xs">
                              {s.content}
                            </pre>
                          </div>
                        ))}
                      </div>
                    </details>
                  )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>你的答案</CardTitle>
                <CardDescription>尽量结构化回答，便于评分。</CardDescription>
              </CardHeader>
              <CardContent className="space-y-3">
                <Textarea
                  rows={8}
                  value={answer}
                  onChange={(e) => setAnswer(e.target.value)}
                  placeholder="在此输入你的回答..."
                />
                <Button
                  type="button"
                  onClick={onEvaluate}
                  disabled={loadingEval}
                >
                  {loadingEval ? "评估中..." : "评估答案"}
                </Button>
              </CardContent>
            </Card>
          </>
        )}

        {evaluation && questionBundle && (
          <Card>
            <CardHeader>
              <CardTitle>评估结果</CardTitle>
              <CardDescription>
                提交后展示期望要点与模型评分（作答前不展示要点）。
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-6">
              <div className="space-y-2">
                <p className="text-sm font-medium">
                  {questionBundle.mode === "seed"
                    ? "期望要点（题库）"
                    : "期望要点（AI 出题）"}
                </p>
                <ul className="list-disc space-y-1 pl-5 text-sm text-muted-foreground">
                  {questionBundle.data.expected_key_points.map((p) => (
                    <li key={p}>{p}</li>
                  ))}
                </ul>
              </div>
              <Separator />
              <div>
                <p className="text-sm text-muted-foreground">分数（满分 10）</p>
                <p className="text-3xl font-semibold tabular-nums">
                  {evaluation.score}
                </p>
              </div>
              <Separator />
              <div className="space-y-2">
                <p className="text-sm font-medium">亮点</p>
                <ul className="list-disc space-y-1 pl-5 text-sm">
                  {evaluation.strengths.map((s) => (
                    <li key={s}>{s}</li>
                  ))}
                </ul>
              </div>
              <div className="space-y-2">
                <p className="text-sm font-medium">缺失或不足</p>
                <ul className="list-disc space-y-1 pl-5 text-sm">
                  {evaluation.missing_points.map((s) => (
                    <li key={s}>{s}</li>
                  ))}
                </ul>
              </div>
              <div className="space-y-2">
                <p className="text-sm font-medium">改进版回答</p>
                <p className="text-sm leading-relaxed whitespace-pre-wrap">
                  {evaluation.improved_answer}
                </p>
              </div>
              {evaluation.weak_topics.length > 0 && (
                <div className="space-y-2">
                  <p className="text-sm font-medium">识别到的薄弱知识点</p>
                  <ul className="list-disc space-y-1 pl-5 text-sm text-muted-foreground">
                    {evaluation.weak_topics.map((w) => (
                      <li key={w}>{w}</li>
                    ))}
                  </ul>
                </div>
              )}
              {(evaluation.study_topics?.length ?? 0) > 0 && (
                <div className="space-y-2">
                  <p className="text-sm font-medium">建议学习方向</p>
                  <ul className="list-disc space-y-1 pl-5 text-sm text-muted-foreground">
                    {(evaluation.study_topics ?? []).map((s) => (
                      <li key={s}>{s}</li>
                    ))}
                  </ul>
                </div>
              )}
              <Separator />
              <details
                className="rounded-lg border border-border bg-card/30 [&_summary::-webkit-details-marker]:hidden"
                open={evidenceOpen}
                onToggle={(e) => setEvidenceOpen(e.currentTarget.open)}
              >
                <summary className="cursor-pointer select-none list-none px-3 py-2.5 text-sm font-medium text-foreground hover:bg-muted/50">
                  引用证据（点击展开或收起）
                </summary>
                <div className="space-y-3 border-t px-3 py-3">
                  {evaluation.reference_evidence.map((s, i) => (
                    <div key={`ev-${i}`} className="space-y-2">
                      <p className="text-xs text-muted-foreground">{s.source}</p>
                      <pre className="whitespace-pre-wrap rounded-md border bg-muted/50 p-3 text-xs leading-relaxed">
                        {s.content}
                      </pre>
                    </div>
                  ))}
                </div>
              </details>
            </CardContent>
          </Card>
        )}
          </>
        )}

        {mainTab === "learn" && (
          <>
            {learnLoadingLabel && (
              <div
                role="status"
                className="flex items-center gap-2 rounded-lg border border-border bg-muted/50 px-4 py-3 text-sm text-muted-foreground"
              >
                <Loader2 className="size-4 shrink-0 animate-spin" aria-hidden />
                <span>{learnLoadingLabel}</span>
              </div>
            )}
            <Card>
              <CardHeader>
                <CardTitle>学习上下文</CardTitle>
                <CardDescription>
                  与「答题」共用同一份 JD 文本（不少于约 40
                  字）。薄弱主题可手动填写；留空则由后端按当前会话薄弱频次推断。计划会先给出对「对方可能更看重什么」的推断，再按你选择的天数排期。
                </CardDescription>
              </CardHeader>
              <CardContent className="flex flex-col gap-4">
                <div className="flex flex-col gap-2">
                  <Label htmlFor="learn-jd">职位描述（JD）</Label>
                  <Textarea
                    id="learn-jd"
                    rows={5}
                    value={jdText}
                    onChange={(e) => setJdText(e.target.value)}
                    placeholder="与答题区相同字段，任一侧编辑会同步……"
                    className="resize-y"
                  />
                </div>
                <div className="flex flex-col gap-2">
                  <Label htmlFor="learn-weak">聚焦薄弱主题（可选）</Label>
                  <input
                    id="learn-weak"
                    type="text"
                    className={selectClass}
                    value={learnWeakTopic}
                    onChange={(e) => setLearnWeakTopic(e.target.value)}
                    placeholder="例如：并发与锁、JVM 内存模型……"
                  />
                </div>
                <div className="flex flex-col gap-2 sm:max-w-md">
                  <Label htmlFor="plan-days">几天内学完本计划</Label>
                  <select
                    id="plan-days"
                    className={selectClass}
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
                        {n} 天
                      </option>
                    ))}
                  </select>
                </div>
                <div className="flex flex-wrap gap-2">
                  <Button
                    type="button"
                    variant="secondary"
                    onClick={onTutorPlan}
                    disabled={loadingPlan || jdText.trim().length < 40}
                  >
                    {loadingPlan ? "生成中…" : "生成学习计划"}
                  </Button>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => {
                      setTutorTurns([]);
                      setTutorFollowups([]);
                      setTutorInput("");
                    }}
                  >
                    清空对话
                  </Button>
                </div>
              </CardContent>
            </Card>

            {learnPlan && (
              <Card>
                <CardHeader>
                  <CardTitle>{learnPlan.plan_title}</CardTitle>
                  <CardDescription>
                    模型推断的侧重点仅供参考；逐日任务应与上方推断一致。
                  </CardDescription>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div className="rounded-md border border-amber-500/30 bg-amber-500/5 p-3">
                    <p className="text-sm font-medium text-amber-900 dark:text-amber-100">
                      侧重点推断（基于 JD 的推测，非事实）
                    </p>
                    <pre className="mt-2 whitespace-pre-wrap text-sm leading-relaxed text-muted-foreground">
                      {learnPlan.jd_priority_guess_markdown}
                    </pre>
                  </div>
                  <ul className="space-y-4 text-sm">
                    {learnPlan.days.map((d) => (
                      <li
                        key={d.day}
                        className="rounded-md border border-border bg-muted/20 p-3"
                      >
                        <p className="font-medium">
                          第 {d.day} 天 · {d.focus}
                        </p>
                        <ul className="mt-2 list-disc space-y-1 pl-5 text-muted-foreground">
                          {d.tasks.map((t) => (
                            <li key={`${d.day}-${t.task}`}>
                              {t.task}{" "}
                              <span className="text-xs">
                                （约 {t.estimated_minutes} 分钟）
                              </span>
                            </li>
                          ))}
                        </ul>
                      </li>
                    ))}
                  </ul>
                  {learnPlan.tips.length > 0 && (
                    <div>
                      <p className="text-sm font-medium">建议</p>
                      <ul className="list-disc space-y-1 pl-5 text-sm text-muted-foreground">
                        {learnPlan.tips.map((t) => (
                          <li key={t}>{t}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                </CardContent>
              </Card>
            )}

            <Card>
              <CardHeader>
                <CardTitle>Tutor 对话</CardTitle>
                <CardDescription>
                  结构化答疑；JD 与薄弱主题会注入上下文（可为空）。
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-3">
                <div className="max-h-72 space-y-3 overflow-y-auto rounded-md border bg-muted/20 p-3 text-sm">
                  {tutorTurns.length === 0 ? (
                    <p className="text-muted-foreground">尚无消息，在下方输入后发送。</p>
                  ) : (
                    tutorTurns.map((t) => (
                      <div
                        key={t.id}
                        className={
                          t.role === "user"
                            ? "rounded-md bg-background/80 p-2"
                            : "rounded-md border border-border bg-card/60 p-2"
                        }
                      >
                        <p className="text-xs font-medium text-muted-foreground">
                          {t.role === "user" ? "你" : "Tutor"}
                        </p>
                        {t.role === "user" ? (
                          <p className="mt-1 whitespace-pre-wrap leading-relaxed">
                            {t.content}
                          </p>
                        ) : (
                          <div className="mt-1 text-sm leading-relaxed [&_*]:break-words">
                            <TutorMarkdown content={t.content} />
                          </div>
                        )}
                      </div>
                    ))
                  )}
                  {tutorLoading && tutorStreamPriming && (
                    <div className="flex items-center gap-2 rounded-md border border-dashed border-border bg-muted/30 px-3 py-2 text-sm text-muted-foreground">
                      <Loader2 className="size-4 animate-spin shrink-0" />
                      <span>Tutor 正在组织回复…</span>
                    </div>
                  )}
                </div>
                {tutorFollowups.length > 0 && (
                  <div>
                    <p className="text-xs font-medium text-muted-foreground">
                      可继续问
                    </p>
                    <ul className="mt-1 list-disc pl-5 text-xs text-muted-foreground">
                      {tutorFollowups.map((f) => (
                        <li key={f}>{f}</li>
                      ))}
                    </ul>
                  </div>
                )}
                <div className="flex flex-col gap-2 sm:flex-row">
                  <Textarea
                    rows={3}
                    value={tutorInput}
                    onChange={(e) => setTutorInput(e.target.value)}
                    placeholder="输入问题后发送……"
                    className="min-h-[4.5rem] flex-1 resize-y"
                  />
                  <Button
                    type="button"
                    className="sm:self-end"
                    onClick={onTutorSend}
                    disabled={tutorLoading}
                  >
                    {tutorLoading ? "发送中…" : "发送"}
                  </Button>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>薄弱主题小测（AI 题）</CardTitle>
                <CardDescription>
                  勾选标签后生成一道 AI 题并评卷，用于巩固「学习」聚焦方向。
                </CardDescription>
              </CardHeader>
              <CardContent className="flex flex-col gap-4">
                <div className="flex flex-col gap-2">
                  <Label>小测标签（多选）</Label>
                  <div className="flex flex-wrap gap-3">
                    {topicOptions.map((opt) => (
                      <label
                        key={`lq-${opt.slug}`}
                        className="flex cursor-pointer items-center gap-2 text-sm"
                      >
                        <input
                          type="checkbox"
                          className="size-4 rounded border-input"
                          checked={learnQuizTopics.includes(opt.slug)}
                          onChange={() => toggleLearnQuizTopic(opt.slug)}
                        />
                        <span>{opt.label}</span>
                      </label>
                    ))}
                  </div>
                </div>
                <div className="flex flex-col gap-4 sm:flex-row sm:flex-wrap sm:items-end">
                  <div className="flex flex-col gap-2">
                    <Label htmlFor="learn-quiz-diff">难度（与答题区同步）</Label>
                    <select
                      id="learn-quiz-diff"
                      className={selectClass}
                      value={difficulty}
                      onChange={(e) =>
                        setDifficulty(e.target.value as Difficulty)
                      }
                    >
                      {DIFFICULTIES.map((d) => (
                        <option key={d} value={d}>
                          {d}
                        </option>
                      ))}
                    </select>
                  </div>
                  <Button
                    type="button"
                    onClick={onGenerateLearnQuiz}
                    disabled={
                      loadingLearnQuizGen || learnQuizTopics.length === 0
                    }
                  >
                    {loadingLearnQuizGen ? "出题中…" : "生成小测题"}
                  </Button>
                </div>
                {learnQuizBundle && (
                  <div className="space-y-3 rounded-md border bg-muted/30 p-3 text-sm">
                    <p className="leading-relaxed">{learnQuizBundle.data.question}</p>
                    <Textarea
                      rows={6}
                      value={learnQuizAnswer}
                      onChange={(e) => setLearnQuizAnswer(e.target.value)}
                      placeholder="小测作答……"
                    />
                    <Button
                      type="button"
                      onClick={onEvaluateLearnQuiz}
                      disabled={loadingLearnQuizEval}
                    >
                      {loadingLearnQuizEval ? "评估中…" : "提交评卷"}
                    </Button>
                    {learnQuizEval && (
                      <div className="space-y-2 border-t pt-3">
                        <p>
                          分数{" "}
                          <span className="font-semibold">{learnQuizEval.score}</span>{" "}
                          /10
                        </p>
                        <div>
                          <p className="text-xs font-medium">改进版回答</p>
                          <p className="whitespace-pre-wrap text-xs leading-relaxed">
                            {learnQuizEval.improved_answer}
                          </p>
                        </div>
                        {(learnQuizEval.study_topics?.length ?? 0) > 0 && (
                          <div>
                            <p className="text-xs font-medium">建议学习方向</p>
                            <ul className="list-disc pl-5 text-xs">
                              {(learnQuizEval.study_topics ?? []).map((s) => (
                                <li key={s}>{s}</li>
                              ))}
                            </ul>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                )}
              </CardContent>
            </Card>
          </>
        )}

        {error && (
          <Card className="border-destructive/50">
            <CardHeader>
              <CardTitle className="text-destructive">请求出错</CardTitle>
            </CardHeader>
            <CardContent>
              <pre className="whitespace-pre-wrap break-words text-sm">
                {error}
              </pre>
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  );
}
