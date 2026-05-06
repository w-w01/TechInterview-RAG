"use client";

import { useCallback, useEffect, useState } from "react";
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
  reference_evidence: ReferenceSnippet[];
};

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

  const selectClass =
    "flex h-10 w-full max-w-md rounded-md border border-input bg-background px-3 py-2 text-sm shadow-xs outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50";

  return (
    <div className="min-h-screen bg-muted/40 px-4 py-10">
      <div className="mx-auto flex w-full max-w-3xl flex-col gap-8">
        <header className="space-y-1">
          <h1 className="text-2xl font-semibold tracking-tight">
            InterviewMate RAG
          </h1>
          <p className="text-sm text-muted-foreground">
            本地演示：可按标签随机/AI 出题，或粘贴 JD
            做向量检索组卷后选题练习；评卷均为 LLM rubric。页面加载时会创建后端练习会话。
          </p>
        </header>

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
