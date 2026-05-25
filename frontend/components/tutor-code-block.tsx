"use client";

import { useCallback, useState } from "react";
import { Check, Copy } from "lucide-react";
import { cn } from "@/lib/utils";

type Props = {
  language?: string;
  children: string;
};

/** 带语言标签与一键复制的代码块 */
export function TutorCodeBlock({ language, children }: Props) {
  const [copied, setCopied] = useState(false);
  const lang = (language ?? "text").replace(/^language-/, "");

  const onCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(children);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      /* 忽略 */
    }
  }, [children]);

  return (
    <div className="learn-code-block group relative mb-3 overflow-hidden rounded-xl border border-border bg-[#1a202c] text-[#e2e8f0] last:mb-0">
      <div className="flex items-center justify-between border-b border-white/10 bg-[#2d3748] px-3 py-1.5">
        <span className="font-mono text-[0.6875rem] uppercase tracking-wide text-[#a0aec0]">
          {lang}
        </span>
        <button
          type="button"
          onClick={() => void onCopy()}
          className="flex items-center gap-1 rounded-md px-2 py-0.5 text-[0.6875rem] text-[#cbd5e0] transition-colors hover:bg-white/10"
        >
          {copied ? (
            <>
              <Check className="size-3" />
              Copied
            </>
          ) : (
            <>
              <Copy className="size-3" />
              Copy
            </>
          )}
        </button>
      </div>
      <pre className="overflow-x-auto p-3">
        <code className={cn("font-mono text-xs leading-relaxed")}>{children}</code>
      </pre>
    </div>
  );
}
