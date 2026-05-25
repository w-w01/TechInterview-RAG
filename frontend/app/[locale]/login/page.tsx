import { setRequestLocale } from "next-intl/server";
import { AuthPageClient } from "@/components/auth/AuthPageClient";

type Props = {
  params: Promise<{ locale: string }>;
};

export default async function LoginPage({ params }: Props) {
  const { locale } = await params;
  setRequestLocale(locale);
  return <AuthPageClient />;
}
