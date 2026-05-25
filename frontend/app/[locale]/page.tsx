import { getTranslations, setRequestLocale } from "next-intl/server";
import { LandingHero } from "@/components/landing/LandingHero";

type Props = {
  params: Promise<{ locale: string }>;
};

export default async function LandingPage({ params }: Props) {
  const { locale } = await params;
  setRequestLocale(locale);
  const t = await getTranslations("landing");
  const base = `/${locale}`;

  return (
    <LandingHero
      headline={t("headline")}
      subtitle={t("subtitle")}
      ctaPrimary={t("ctaPrimary")}
      ctaHref={`${base}/session`}
    />
  );
}
