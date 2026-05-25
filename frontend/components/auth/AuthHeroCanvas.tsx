"use client";

import { Brain, Waves, Zap } from "lucide-react";
import { useTranslations } from "next-intl";
const HERO_SPECS = [
  { key: "heroSpec1" as const, Icon: Zap },
  { key: "heroSpec2" as const, Icon: Brain },
  { key: "heroSpec3" as const, Icon: Waves },
] as const;

/** 左侧文案层（粒子由 AuthParticleCanvas 独立渲染） */
export function AuthHeroCanvas() {
  const t = useTranslations("auth");

  return (
    <div className="auth-hero relative flex h-full min-h-0 w-full flex-col justify-between overflow-hidden p-10 text-[#e8fff8]">
      <div className="relative z-10 max-w-xl">
        <span className="auth-engine-badge">{t("heroBadge")}</span>
        <h2 className="auth-hero-title mt-8">
          <span className="block">{t("heroTitleLine1")}</span>
          <span className="block">{t("heroTitleLine2")}</span>
        </h2>
        <ul className="auth-hero-specs mt-10 space-y-4" role="list">
          {HERO_SPECS.map(({ key, Icon }) => (
            <li key={key} className="auth-hero-spec-item flex items-start gap-3">
              <Icon
                className="mt-0.5 size-4 shrink-0 text-[#50ffd2]"
                strokeWidth={1.75}
                aria-hidden
              />
              <span>{t(key)}</span>
            </li>
          ))}
        </ul>
      </div>
      <p className="auth-hero-footer pointer-events-none relative z-10">
        {t("heroFooter")}
      </p>
    </div>
  );
}
