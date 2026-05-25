"use client";

import { cn } from "@/lib/utils";

/** 学习计划生成中的骨架屏（微光闪烁） */
export function PlanSkeleton({ className }: { className?: string }) {
  return (
    <div className={cn("learn-plan-skeleton space-y-4", className)}>
      {Array.from({ length: 4 }).map((_, i) => (
        <div
          key={i}
          className="learn-skeleton-shimmer rounded-2xl border border-border/60 bg-muted/40 p-4"
          style={{ animationDelay: `${i * 120}ms` }}
        >
          <div className="mb-3 h-3 w-24 rounded-full bg-muted" />
          <div className="mb-2 h-4 w-full max-w-[90%] rounded-md bg-muted" />
          <div className="h-3 w-2/3 rounded-md bg-muted/80" />
        </div>
      ))}
    </div>
  );
}
