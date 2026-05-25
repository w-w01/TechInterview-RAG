import { setRequestLocale } from "next-intl/server";
import { LearnClient } from "@/components/learn/LearnClient";

type Props = {
  params: Promise<{ locale: string }>;
};

export default async function LearnPage({ params }: Props) {
  const { locale } = await params;
  setRequestLocale(locale);
  return <LearnClient />;
}
