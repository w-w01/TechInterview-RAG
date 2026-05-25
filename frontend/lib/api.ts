import type { AppLocale } from "@/i18n/routing";
import { uiLocaleToApiMode } from "@/lib/locale";
import type {
  Difficulty,
  EvaluateResponse,
  GenerateLlmResponse,
  GenerateResponse,
  PaperBuildMeta,
  PaperQuestion,
  TutorPlanResponse,
} from "@/lib/types";

export function apiBase(): string {
  return process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${apiBase()}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || res.statusText);
  }
  return res.json() as Promise<T>;
}

export async function fetchTopics(): Promise<
  { slug: string; label: string }[]
> {
  const res = await fetch(`${apiBase()}/topics`);
  if (!res.ok) return [];
  const data = (await res.json()) as { topics: { slug: string; label: string }[] };
  return data.topics ?? [];
}

export async function createSession(): Promise<string | null> {
  try {
    const data = await postJson<{ session_id: string }>("/sessions", {});
    return data.session_id?.trim() || null;
  } catch {
    return null;
  }
}

export async function generatePaperFromJd(params: {
  jd_text: string;
  difficulty: Difficulty;
  count: number;
  session_id?: string;
}): Promise<{ questions: PaperQuestion[]; meta: PaperBuildMeta }> {
  return postJson("/generate-paper-from-jd", params);
}

export async function generateQuestionSeed(params: {
  topics: string[];
  difficulty: Difficulty;
  session_id?: string;
}): Promise<GenerateResponse> {
  return postJson("/generate-question", params);
}

export async function generateQuestionLlm(params: {
  topics: string[];
  difficulty: Difficulty;
  session_id?: string;
  reference_max?: number;
}): Promise<GenerateLlmResponse> {
  return postJson("/generate-question-llm", {
    reference_max: 5,
    ...params,
  });
}

export async function evaluateAnswer(
  payload: Record<string, unknown>,
): Promise<EvaluateResponse> {
  return postJson("/evaluate-answer", payload);
}

export async function tutorLearningPlan(params: {
  sessionId: string;
  jd_text: string;
  weak_topic: string;
  plan_days: number;
  locale: AppLocale;
}): Promise<TutorPlanResponse> {
  return postJson(
    `/sessions/${params.sessionId}/tutor/learning-plan`,
    {
      jd_text: params.jd_text,
      weak_topic: params.weak_topic,
      plan_days: params.plan_days,
      locale_mode: uiLocaleToApiMode(params.locale),
    },
  );
}

export function paperQuestionKey(q: PaperQuestion): string {
  if (q.source === "seed") return `seed:${q.question_id ?? ""}`;
  return `llm:${q.generation_id ?? ""}`;
}

export function buildEvaluatePayload(
  q: PaperQuestion,
  studentAnswer: string,
  sessionId?: string | null,
): Record<string, unknown> {
  const base = {
    question: q.question,
    student_answer: studentAnswer,
    topics: q.topics,
    difficulty: q.difficulty,
    ...(sessionId ? { session_id: sessionId } : {}),
  };
  if (q.source === "seed") {
    return { ...base, question_id: q.question_id };
  }
  return { ...base, generation_id: q.generation_id };
}
