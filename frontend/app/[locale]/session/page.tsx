import { Suspense } from "react";
import { setRequestLocale } from "next-intl/server";
import { SessionPageClient } from "@/components/session/SessionPageClient";
import { Loader2 } from "lucide-react";

type Props = {
  params: Promise<{ locale: string }>;
};

export default async function SessionPage({ params }: Props) {
  const { locale } = await params;
  setRequestLocale(locale);
  return (
    <Suspense
      fallback={
        <div className="flex items-center gap-2 text-muted-foreground">
          <Loader2 className="size-4 animate-spin" />
        </div>
      }
    >
      <SessionPageClient />
    </Suspense>
  );
}
