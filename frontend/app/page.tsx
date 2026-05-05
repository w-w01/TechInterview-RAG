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

type EvaluateResponse = {
  score: number;
  strengths: string[];
  missing_points: string[];
  improved_answer: string;
  reference_evidence: ReferenceSnippet[];
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
  const [difficulty, setDifficulty] = useState<Difficulty>("beginner");
  const [questionPayload, setQuestionPayload] = useState<GenerateResponse | null>(
    null,
  );
  const [answer, setAnswer] = useState("");
  const [evaluation, setEvaluation] = useState<EvaluateResponse | null>(null);
  const [loadingGen, setLoadingGen] = useState(false);
  const [loadingEval, setLoadingEval] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [evidenceOpen, setEvidenceOpen] = useState(true);

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
    if (evaluation) setEvidenceOpen(true);
  }, [evaluation]);

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

  const onGenerate = useCallback(async () => {
    setError(null);
    setEvaluation(null);
    setLoadingGen(true);
    try {
      const res = await fetch(`${apiBase()}/generate-question`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ topics: selectedTopics, difficulty }),
      });
      if (!res.ok) {
        const text = await res.text();
        throw new Error(text || res.statusText);
      }
      const data = (await res.json()) as GenerateResponse;
      setQuestionPayload(data);
      setSessionTopics([...selectedTopics]);
      setAnswer("");
    } catch (e) {
      setQuestionPayload(null);
      setSessionTopics([]);
      setError(e instanceof Error ? e.message : "Generate failed");
    } finally {
      setLoadingGen(false);
    }
  }, [selectedTopics, difficulty]);

  const onEvaluate = useCallback(async () => {
    if (!questionPayload) {
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
      const res = await fetch(`${apiBase()}/evaluate-answer`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question_id: questionPayload.question_id,
          question: questionPayload.question,
          student_answer: answer,
          topics: sessionTopics,
          difficulty: questionPayload.difficulty,
        }),
      });
      if (!res.ok) {
        const text = await res.text();
        throw new Error(text || res.statusText);
      }
      const data = (await res.json()) as EvaluateResponse;
      setEvaluation(data);
    } catch (e) {
      setEvaluation(null);
      setError(e instanceof Error ? e.message : "Evaluate failed");
    } finally {
      setLoadingEval(false);
    }
  }, [answer, questionPayload, sessionTopics]);

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
            本地演示：可多选标签（OR）与难度、生成面试题、提交答案后获得评分与改进建议。
          </p>
        </header>

        <Card>
          <CardHeader>
            <CardTitle>练习设置</CardTitle>
            <CardDescription>
              勾选至少一个主题标签（与题库条目的 topics 求交集后随机抽题），再选难度并生成。
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
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

        {questionPayload && (
          <>
            <Card>
              <CardHeader>
                <CardTitle>面试题</CardTitle>
                <CardDescription>
                  {questionPayload.topics.map(labelForSlug).join(" · ")} /{" "}
                  {questionPayload.difficulty} / {questionPayload.question_id}
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <p className="text-sm leading-relaxed">
                  {questionPayload.question}
                </p>
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

        {evaluation && questionPayload && (
          <Card>
            <CardHeader>
              <CardTitle>评估结果</CardTitle>
              <CardDescription>
                提交后展示题库期望要点与模型评分（作答前不展示要点）。
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-6">
              <div className="space-y-2">
                <p className="text-sm font-medium">期望要点（题库）</p>
                <ul className="list-disc space-y-1 pl-5 text-sm text-muted-foreground">
                  {questionPayload.expected_key_points.map((p) => (
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
