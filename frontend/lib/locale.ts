import type { AppLocale } from "@/i18n/routing";

/** UI locale 映射为 Tutor API 的 locale_mode */
export function uiLocaleToApiMode(locale: AppLocale): "zh" | "en" {
  return locale === "en" ? "en" : "zh";
}
