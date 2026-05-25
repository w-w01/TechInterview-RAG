import Link from "next/link";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

type Props = {
  headline: string;
  subtitle: string;
  ctaPrimary: string;
  ctaHref: string;
};

export function LandingHero({
  headline,
  subtitle,
  ctaPrimary,
  ctaHref,
}: Props) {
  return (
    <section className="flex flex-col items-center pb-20 pt-12 text-center md:pt-16">
      <div className="max-w-4xl">
        <h1 className="font-sans text-3xl font-extrabold uppercase leading-tight tracking-tight text-dark sm:text-4xl md:text-5xl lg:text-[2.75rem]">
          {headline}
        </h1>
        <p className="mx-auto mt-5 max-w-2xl font-sans text-base leading-relaxed text-dark-muted md:text-lg">
          {subtitle}
        </p>
        <div className="mt-8">
          <Link
            href={ctaHref}
            className={cn(
              buttonVariants({ size: "lg" }),
              "rounded-full bg-brand px-8 font-sans text-base font-semibold text-white shadow-[0_4px_14px_rgb(0_154_115/0.35)] transition-transform duration-200 hover:scale-105 hover:bg-brand-dark",
            )}
          >
            {ctaPrimary}
          </Link>
        </div>
      </div>
    </section>
  );
}
