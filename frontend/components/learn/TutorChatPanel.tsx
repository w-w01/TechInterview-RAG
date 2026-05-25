"use client";

import {
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import { useTranslations } from "next-intl";
import { ArrowDown, Bot, Loader2, Send } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { TutorMarkdown } from "@/components/tutor-markdown";
import { useLearn } from "@/components/learn/LearnProvider";
import { cn } from "@/lib/utils";

const SCROLL_THRESHOLD = 72;

export function TutorChatPanel() {
  const t = useTranslations("learn");
  const tc = useTranslations("common");
  const {
    tutorTurns,
    tutorInput,
    setTutorInput,
    tutorLoading,
    tutorStreamPriming,
    tutorFollowups,
    tutorRagMeta,
    sendTutorMessage,
    clearTutorChat,
    error,
    setError,
  } = useLearn();

  const scrollRef = useRef<HTMLDivElement>(null);
  const [pinnedToBottom, setPinnedToBottom] = useState(true);
  const [showNewMessages, setShowNewMessages] = useState(false);
  const lastScrollTopRef = useRef(0);

  const isNearBottom = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return true;
    return el.scrollHeight - el.scrollTop - el.clientHeight < SCROLL_THRESHOLD;
  }, []);

  const scrollToBottom = useCallback((behavior: ScrollBehavior = "smooth") => {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTo({ top: el.scrollHeight, behavior });
    setShowNewMessages(false);
    setPinnedToBottom(true);
  }, []);

  const onScroll = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    const near = isNearBottom();
    const scrollingUp = el.scrollTop < lastScrollTopRef.current - 2;
    lastScrollTopRef.current = el.scrollTop;
    setPinnedToBottom(near);
    if (scrollingUp && !near) {
      setShowNewMessages(true);
    }
    if (near) {
      setShowNewMessages(false);
    }
  }, [isNearBottom]);

  useEffect(() => {
    if (pinnedToBottom) {
      scrollToBottom(tutorLoading ? "auto" : "smooth");
    } else if (tutorTurns.length > 0) {
      setShowNewMessages(true);
    }
  }, [tutorTurns, tutorLoading, tutorStreamPriming, pinnedToBottom, scrollToBottom]);

  const onSubmit = () => {
    void sendTutorMessage(tutorInput);
  };

  const showWelcome = tutorTurns.length === 0 && !tutorLoading;

  return (
    <div className="learn-tutor flex h-full max-h-full min-h-0 flex-col overflow-hidden rounded-3xl border border-border/80 bg-card shadow-[0_8px_32px_rgb(26_32_44/0.08)]">
      <div className="flex shrink-0 items-center justify-between border-b border-border/70 px-5 py-3">
        <div>
          <h2 className="text-sm font-semibold uppercase tracking-wider text-dark-muted">
            {t("tutorTitle")}
          </h2>
          <p className="mt-0.5 text-xs text-dark-light">{t("tutorDesc")}</p>
        </div>
        <Button type="button" variant="ghost" size="sm" onClick={clearTutorChat}>
          {t("clearChat")}
        </Button>
      </div>

      <div className="relative min-h-0 flex-1 overflow-hidden">
        <div
          ref={scrollRef}
          onScroll={onScroll}
          className="absolute inset-0 overflow-y-auto px-5 py-4"
        >
          {showWelcome && (
            <div className="flex min-h-0 flex-1 flex-col items-center justify-center py-8 text-center">
              <div className="mb-4 flex size-14 items-center justify-center rounded-2xl bg-primary/10 text-primary">
                <Bot className="size-8" strokeWidth={1.5} />
              </div>
              <h3 className="text-lg font-semibold text-dark">
                {t("welcomeTitle")}
              </h3>
              <p className="mt-2 max-w-md text-sm leading-relaxed text-dark-muted">
                {t("welcomeBody")}
              </p>
            </div>
          )}

          <div className="space-y-4">
            {tutorTurns.map((turn) => (
              <div
                key={turn.id}
                className={cn(
                  "flex",
                  turn.role === "user" ? "justify-end" : "justify-start",
                )}
              >
                <div
                  className={cn(
                    "max-w-[92%] rounded-2xl px-4 py-3 text-sm leading-relaxed",
                    turn.role === "user"
                      ? "bg-primary text-primary-foreground"
                      : "border border-border bg-muted/30 text-dark",
                  )}
                >
                  <p className="mb-1 text-[0.6875rem] font-medium opacity-70">
                    {turn.role === "user" ? t("you") : t("tutor")}
                  </p>
                  {turn.role === "user" ? (
                    <p className="whitespace-pre-wrap">{turn.content}</p>
                  ) : (
                    <TutorMarkdown content={turn.content} />
                  )}
                </div>
              </div>
            ))}

            {tutorLoading && tutorStreamPriming && (
              <div className="flex items-center gap-2 text-sm text-dark-muted">
                <Loader2 className="size-4 animate-spin" />
                <span>{t("tutorReplying")}</span>
              </div>
            )}
          </div>

          {tutorFollowups.length > 0 && (
            <div className="mt-4 flex flex-wrap gap-2">
              {tutorFollowups.map((f) => (
                <button
                  key={f}
                  type="button"
                  className="rounded-full border border-border bg-background px-3 py-1 text-xs text-dark-muted transition-colors hover:border-primary/40 hover:text-primary"
                  onClick={() => void sendTutorMessage(f)}
                >
                  {f}
                </button>
              ))}
            </div>
          )}

          {tutorRagMeta && (
            <details className="mt-4 rounded-xl border border-border/80 bg-muted/20 text-xs">
              <summary className="cursor-pointer px-3 py-2 font-medium text-dark-muted">
                {t("retrievalDetails")}
              </summary>
              <div className="space-y-2 border-t border-border/70 px-3 py-3 text-dark-light">
                <p>
                  {t("rewriteChanged", {
                    value: tutorRagMeta.rewrite_changed ? t("yes") : t("no"),
                  })}
                </p>
                <p className="whitespace-pre-wrap">
                  {tutorRagMeta.rewritten_query || "—"}
                </p>
              </div>
            </details>
          )}
        </div>

        {showNewMessages && !pinnedToBottom && (
          <button
            type="button"
            onClick={() => scrollToBottom()}
            className="absolute bottom-4 left-1/2 z-10 flex -translate-x-1/2 items-center gap-1.5 rounded-full border border-primary/30 bg-background px-3 py-1.5 text-xs font-medium text-primary shadow-md transition-transform hover:scale-105"
          >
            <ArrowDown className="size-3.5" />
            {t("newMessages")}
          </button>
        )}
      </div>

      <div className="shrink-0 border-t border-border/70 p-3">
        {error && (
          <p className="mb-2 text-xs text-destructive" role="alert">
            {error}
          </p>
        )}
        <div className="flex gap-2">
          <Textarea
            rows={2}
            value={tutorInput}
            onChange={(e) => {
              setTutorInput(e.target.value);
              setError(null);
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                onSubmit();
              }
            }}
            placeholder={t("inputPlaceholder")}
            className="min-h-[3.25rem] flex-1 resize-none rounded-xl"
            disabled={tutorLoading}
          />
          <Button
            type="button"
            className="h-auto shrink-0 self-end rounded-xl px-4"
            onClick={onSubmit}
            disabled={tutorLoading || !tutorInput.trim()}
          >
            {tutorLoading ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <Send className="size-4" />
            )}
            <span className="sr-only">{tutorLoading ? t("sending") : t("send")}</span>
          </Button>
        </div>
        <p className="mt-2 text-[0.6875rem] text-dark-light">{tc("feedbackLocaleHint")}</p>
      </div>
    </div>
  );
}
