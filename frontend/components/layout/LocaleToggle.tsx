"use client";

import { useLocale } from "next-intl";
import { usePathname, useRouter } from "next/navigation";
import type { AppLocale } from "@/i18n/routing";
import { cn } from "@/lib/utils";

type Props = {
  labels: { zh: string; en: string };
};

export function LocaleToggle({ labels }: Props) {
  const locale = useLocale() as AppLocale;
  const router = useRouter();
  const pathname = usePathname();

  const switchTo = (next: AppLocale) => {
    if (next === locale) return;
    const segments = pathname.split("/");
    if (segments[1] === "zh" || segments[1] === "en") {
      segments[1] = next;
    } else {
      segments.splice(1, 0, next);
    }
    const nextPath = segments.join("/") || `/${next}`;
    document.cookie = `NEXT_LOCALE=${next};path=/;max-age=31536000`;
    router.replace(nextPath);
  };

  return (
    <div className="flex items-center gap-2 text-sm text-dark-muted">
      <button
        type="button"
        onClick={() => switchTo("zh")}
        className={cn(
          "transition-colors hover:text-dark",
          locale === "zh" && "font-semibold text-dark",
        )}
      >
        {labels.zh}
      </button>
      <span className="text-dark-light" aria-hidden>
        |
      </span>
      <button
        type="button"
        onClick={() => switchTo("en")}
        className={cn(
          "transition-colors hover:text-dark",
          locale === "en" && "font-semibold text-dark",
        )}
      >
        {labels.en}
      </button>
    </div>
  );
}
