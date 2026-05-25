"use client";

import type { Components } from "react-markdown";
import ReactMarkdown from "react-markdown";
import rehypeSanitize from "rehype-sanitize";
import remarkGfm from "remark-gfm";
import { TutorCodeBlock } from "@/components/tutor-code-block";

const markdownComponents: Partial<Components> = {
  h1: ({ children }) => (
    <h1 className="mb-2 mt-3 text-base font-semibold tracking-tight first:mt-0">
      {children}
    </h1>
  ),
  h2: ({ children }) => (
    <h2 className="mb-2 mt-3 text-[0.95rem] font-semibold tracking-tight first:mt-0">
      {children}
    </h2>
  ),
  h3: ({ children }) => (
    <h3 className="mb-1.5 mt-2 text-sm font-semibold first:mt-0">{children}</h3>
  ),
  h4: ({ children }) => (
    <h4 className="mb-1.5 mt-2 text-sm font-medium first:mt-0">{children}</h4>
  ),
  p: ({ children }) => (
    <p className="mb-2 leading-relaxed last:mb-0">{children}</p>
  ),
  ul: ({ children }) => (
    <ul className="mb-2 list-disc space-y-1 pl-5 last:mb-0">{children}</ul>
  ),
  ol: ({ children }) => (
    <ol className="mb-2 list-decimal space-y-1 pl-5 last:mb-0">{children}</ol>
  ),
  li: ({ children }) => <li className="leading-relaxed">{children}</li>,
  blockquote: ({ children }) => (
    <blockquote className="mb-2 border-l-2 border-muted-foreground/30 pl-3 text-muted-foreground last:mb-0">
      {children}
    </blockquote>
  ),
  a: ({ href, children }) => (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="font-medium text-primary underline underline-offset-2"
    >
      {children}
    </a>
  ),
  strong: ({ children }) => (
    <strong className="font-semibold">{children}</strong>
  ),
  em: ({ children }) => <em className="italic">{children}</em>,
  hr: () => <hr className="my-3 border-border" />,
  table: ({ children }) => (
    <div className="mb-2 max-w-full overflow-x-auto last:mb-0">
      <table className="w-full border-collapse border border-border text-left text-xs">
        {children}
      </table>
    </div>
  ),
  thead: ({ children }) => <thead className="bg-muted/50">{children}</thead>,
  tbody: ({ children }) => <tbody>{children}</tbody>,
  tr: ({ children }) => <tr className="border-b border-border">{children}</tr>,
  th: ({ children }) => (
    <th className="border border-border px-2 py-1.5 font-semibold">{children}</th>
  ),
  td: ({ children }) => (
    <td className="border border-border px-2 py-1.5">{children}</td>
  ),
  pre: ({ children }) => <>{children}</>,
  code: ({ className, children, ...props }) => {
    const flat = Array.isArray(children)
      ? children.map((c) => (typeof c === "string" ? c : "")).join("")
      : String(children ?? "");
    const hasLang =
      typeof className === "string" && className.includes("language-");
    const isBlock = hasLang || flat.includes("\n");

    if (isBlock) {
      const lang =
        typeof className === "string"
          ? className.replace(/.*language-(\S+).*/, "$1")
          : undefined;
      return <TutorCodeBlock language={lang}>{flat.replace(/\n$/, "")}</TutorCodeBlock>;
    }
    return (
      <code
        className="rounded bg-muted px-1 py-0.5 font-mono text-[0.9em]"
        {...props}
      >
        {children}
      </code>
    );
  },
};

type TutorMarkdownProps = {
  content: string;
};

export function TutorMarkdown({ content }: TutorMarkdownProps) {
  if (!content.trim()) {
    return null;
  }
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      rehypePlugins={[rehypeSanitize]}
      components={markdownComponents}
    >
      {content}
    </ReactMarkdown>
  );
}
