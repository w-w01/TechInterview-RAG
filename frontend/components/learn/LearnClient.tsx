"use client";

import { useTranslations } from "next-intl";
import { LearnProvider } from "@/components/learn/LearnProvider";
import { SyllabusPanel } from "@/components/learn/SyllabusPanel";
import { TutorChatPanel } from "@/components/learn/TutorChatPanel";
function LearnLayout() {
  const t = useTranslations("learn");

  return (
    <div className="learn-page flex h-full min-h-0 flex-col gap-3 overflow-hidden">
      <header className="shrink-0 space-y-0.5">
        <h1 className="text-xl font-bold tracking-tight text-dark sm:text-2xl">
          {t("title")}
        </h1>
        <p className="text-xs text-dark-muted sm:text-sm">{t("subtitle")}</p>
      </header>

      <div className="learn-columns grid h-0 min-h-0 flex-1 grid-cols-1 grid-rows-[minmax(0,1fr)_minmax(0,1fr)] gap-3 overflow-hidden lg:grid-cols-[minmax(300px,38%)_minmax(0,1fr)] lg:grid-rows-[minmax(0,1fr)] lg:gap-4">
        <SyllabusPanel />
        <TutorChatPanel />
      </div>
    </div>
  );
}

export function LearnClient() {
  return (
    <LearnProvider>
      <LearnLayout />
    </LearnProvider>
  );
}
