import Link from "next/link";
import { InterviewMateLogo } from "@/components/layout/InterviewMateLogo";
import { cn } from "@/lib/utils";

type Props = {
  href: string;
  className?: string;
};

export function BrandLogo({ href, className }: Props) {
  return (
    <Link
      href={href}
      className={cn("inline-flex shrink-0 items-center", className)}
    >
      <InterviewMateLogo />
    </Link>
  );
}
