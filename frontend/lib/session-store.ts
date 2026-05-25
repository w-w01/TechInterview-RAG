import type { EvaluateResponse, GradingEntry, GradingStatus } from "@/lib/types";

/** 场次评卷状态（内存；刷新后需从 API 重拉） */
export type GradingStore = Map<string, GradingEntry>;

export function createGradingEntry(answer: string): GradingEntry {
  return { status: "pending", answer };
}

export function setGradingScoring(store: GradingStore, key: string): void {
  const prev = store.get(key);
  if (prev) store.set(key, { ...prev, status: "scoring" });
}

export function setGradingDone(
  store: GradingStore,
  key: string,
  result: EvaluateResponse,
): void {
  const prev = store.get(key);
  store.set(key, {
    answer: prev?.answer ?? "",
    status: "done",
    result,
  });
}

export function setGradingError(
  store: GradingStore,
  key: string,
  error: string,
): void {
  const prev = store.get(key);
  store.set(key, {
    answer: prev?.answer ?? "",
    status: "error",
    error,
  });
}

export function countByStatus(
  store: GradingStore,
  status: GradingStatus,
): number {
  let n = 0;
  store.forEach((e) => {
    if (e.status === status) n++;
  });
  return n;
}

/** 评卷并发上限 */
export const GRADING_CONCURRENCY = 2;
