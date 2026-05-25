"use client";

import { useEffect } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";
import { BrandLogo } from "@/components/layout/BrandLogo";
import { LocaleToggle } from "@/components/layout/LocaleToggle";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

type Props = {
  children: React.ReactNode;
};

const navItems = [
  { key: "home", href: "" },
  { key: "session", href: "/session" },
  { key: "learn", href: "/learn" },
] as const;

export function AppShell({ children }: Props) {
  const t = useTranslations("nav");
  const locale = useLocale();
  const pathname = usePathname();
  const base = `/${locale}`;
  const isLanding = pathname === base || pathname === `${base}/`;
  const isLearn = pathname.startsWith(`${base}/learn`);
  const isAuth = pathname.startsWith(`${base}/login`);

  useEffect(() => {
    document.documentElement.lang = locale;
  }, [locale]);

  const isActive = (href: string) => {
    const full = href ? `${base}${href}` : base;
    if (href === "") return pathname === base || pathname === `${base}/`;
    return pathname.startsWith(full);
  };

  if (isAuth) {
    return <>{children}</>;
  }

  return (
    <div
      className={cn(
        "im-surface relative",
        isLearn ? "flex h-dvh flex-col overflow-hidden" : "min-h-screen",
      )}
    >
      <header className="z-50 shrink-0 border-b border-border/80 bg-white/70 backdrop-blur-[4px]">
        <div className="mx-auto flex h-16 max-w-6xl items-center justify-between gap-4 px-4 md:px-6">
          <BrandLogo href={base} />

          <nav className="absolute left-1/2 hidden -translate-x-1/2 items-center gap-1 md:flex">
            {navItems.map((item) => (
              <Link
                key={item.key}
                href={item.href ? `${base}${item.href}` : base}
                className={
                  isActive(item.href) ? "im-nav-pill-active" : "im-nav-pill"
                }
              >
                {t(item.key)}
              </Link>
            ))}
          </nav>

          <div className="flex items-center gap-4">
            <LocaleToggle labels={{ zh: t("langZh"), en: t("langEn") }} />
            <Link
              href={`${base}/login`}
              className={cn(
                buttonVariants({ variant: "outline", size: "sm" }),
                "hidden rounded-full border-dark/20 px-5 font-medium text-dark hover:bg-muted sm:inline-flex",
              )}
            >
              {t("signUp")}
            </Link>
          </div>
        </div>

        <nav className="flex gap-1 overflow-x-auto border-t border-border/60 px-4 py-2 md:hidden">
          {navItems.map((item) => (
            <Link
              key={item.key}
              href={item.href ? `${base}${item.href}` : base}
              className={cn(
                "shrink-0 rounded-full px-3 py-1.5 text-xs",
                isActive(item.href)
                  ? "bg-muted font-medium text-dark"
                  : "text-dark-muted",
              )}
            >
              {t(item.key)}
            </Link>
          ))}
        </nav>
      </header>

      <main
        className={cn(
          "mx-auto w-full px-4 md:px-6",
          isLanding && "max-w-6xl py-0",
          isLearn &&
            "flex min-h-0 flex-1 flex-col overflow-hidden py-2 md:max-w-6xl md:py-3",
          !isLanding && !isLearn && "max-w-5xl py-8",
        )}
      >
        {children}
      </main>
    </div>
  );
}
