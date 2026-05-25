export const DIFFICULTIES = ["beginner", "intermediate", "advanced"] as const;
export type Difficulty = (typeof DIFFICULTIES)[number];

export type TopicOption = { slug: string; label: string };

export type ReferenceSnippet = { source: string; content: string };

export type GenerateResponse = {
  question_id: string;
  question: string;
  topics: string[];
  difficulty: string;
  expected_key_points: string[];
};

export type GenerateLlmResponse = {
  generation_id: string;
  question: string;
  topics: string[];
  difficulty: string;
  expected_key_points: string[];
  reference_snippets: ReferenceSnippet[];
  source_seed_ids: string[];
};

export type PaperQuestion = {
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

export type PaperBuildMeta = {
  seed_count: number;
  ai_count: number;
  ai_ratio: number;
  ai_ratio_boosted: boolean;
  ai_ratio_reason: string;
  seen_ratio_in_candidates: number;
  unseen_candidate_count: number;
  weak_topics_used: string[];
  topic_priority: string[];
  baseline_window: number;
  topic_level_plan: Record<string, string>;
  adjustment_reasons: string[];
  planner_notes?: string[];
  selector_notes?: string;
  selector_candidate_count?: number;
  program_fixes?: string[];
};

export type QuestionBundle =
  | { mode: "seed"; data: GenerateResponse }
  | { mode: "llm"; data: GenerateLlmResponse };

export type QuestionSource = "seed" | "llm";

export type EvaluateResponse = {
  score: number;
  strengths: string[];
  missing_points: string[];
  improved_answer: string;
  weak_topics: string[];
  study_topics?: string[];
  reference_evidence: ReferenceSnippet[];
};

export type TutorPlanResponse = {
  plan_title: string;
  jd_priority_guess_markdown: string;
  days: {
    day: number;
    focus: string;
    tasks: { task: string; estimated_minutes: number }[];
  }[];
  tips: string[];
};

export type TutorTurn = { id: string; role: string; content: string };

export type TutorRagMeta = {
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

export type SessionQuestion = PaperQuestion;

export type GradingStatus = "pending" | "scoring" | "done" | "error";

export type GradingEntry = {
  status: GradingStatus;
  answer: string;
  result?: EvaluateResponse;
  error?: string;
};

export type SessionSource = "jd" | "topics";
