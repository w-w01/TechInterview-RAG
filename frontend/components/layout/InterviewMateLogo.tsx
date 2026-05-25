import { cn } from "@/lib/utils";

type Props = {
  className?: string;
  title?: string;
};

/** 图标与 Mate 共用色标；Mate 渐变与青蓝拱形同方向、同 stops */
const GRADIENT_STOPS = (
  <>
    <stop offset="0%" stopColor="#009A73" />
    <stop offset="100%" stopColor="#40B7E1" />
  </>
);

export function InterviewMateLogo({ className, title = "InterviewMate" }: Props) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 160 36"
      width={160}
      height={36}
      fill="none"
      className={cn("interviewmate-logo h-9 w-auto", className)}
      role="img"
      aria-label={title}
    >
      <title>{title}</title>
      <defs>
        <linearGradient
          id="interviewmate-icon-gradient"
          gradientUnits="userSpaceOnUse"
          x1="23"
          y1="8"
          x2="34"
          y2="30"
        >
          {GRADIENT_STOPS}
        </linearGradient>
        <linearGradient
          id="interviewmate-mate-gradient"
          gradientUnits="userSpaceOnUse"
          x1="108"
          y1="8"
          x2="148"
          y2="30"
        >
          {GRADIENT_STOPS}
        </linearGradient>
      </defs>
      <g transform="translate(2, 4)">
        <circle cx="5" cy="4" r="3.5" fill="#1A202C" />
        <path
          d="M2.25 11C2.25 9.89543 3.14543 9 5 9C6.85457 9 7.75 9.89543 7.75 11V26H2.25V11Z"
          fill="url(#interviewmate-icon-gradient)"
        />
        <path
          d="M10.5 10C10.5 6.23858 12.7386 4 15.5 4C18.2614 4 20.5 6.23858 20.5 10V26H15.5V12C15.5 11.4477 15.0523 11 14.5 11C13.9477 11 13.5 11.4477 13.5 12V26H10.5V10Z"
          fill="#1A202C"
        />
        <path
          d="M21.5 10C21.5 6.23858 23.7386 4 26.5 4C29.2614 4 31.5 6.23858 31.5 10V26H26.5V12C26.5 11.4477 26.0523 11 25.5 11C24.9477 11 24.5 11.4477 24.5 12V26H21.5V10Z"
          fill="url(#interviewmate-icon-gradient)"
        />
      </g>
      <text
        x="44"
        y="24"
        fontFamily="var(--font-inter), Inter, -apple-system, BlinkMacSystemFont, sans-serif"
        fontSize="16"
        fontWeight="800"
        fill="#1A202C"
        letterSpacing="-0.03em"
      >
        Interview
        <tspan fontWeight="600" fill="url(#interviewmate-mate-gradient)">
          Mate
        </tspan>
      </text>
    </svg>
  );
}
