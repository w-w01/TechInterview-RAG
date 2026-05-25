"use client";

import { useCallback, useState } from "react";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";

type Props = {
  id?: string;
  tags: string[];
  onChange: (tags: string[]) => void;
  placeholder?: string;
  disabled?: boolean;
  className?: string;
};

/** 高亮 Tag 输入：Enter / 逗号添加，点击标签删除 */
export function TagInput({
  id,
  tags,
  onChange,
  placeholder,
  disabled,
  className,
}: Props) {
  const [draft, setDraft] = useState("");

  const addTag = useCallback(
    (raw: string) => {
      const t = raw.trim().replace(/[,，;；]/g, "");
      if (!t || tags.includes(t)) return;
      onChange([...tags, t]);
      setDraft("");
    },
    [tags, onChange],
  );

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault();
      addTag(draft);
    } else if (e.key === "Backspace" && !draft && tags.length > 0) {
      onChange(tags.slice(0, -1));
    }
  };

  return (
    <div
      className={cn(
        "flex min-h-11 w-full flex-wrap items-center gap-2 rounded-xl border border-border/80 bg-background px-3 py-2 shadow-xs transition-colors focus-within:border-primary/50 focus-within:ring-[3px] focus-within:ring-primary/15",
        disabled && "pointer-events-none opacity-60",
        className,
      )}
    >
      {tags.map((tag) => (
        <span
          key={tag}
          className="inline-flex items-center gap-1 rounded-full border border-primary/25 bg-primary/10 px-2.5 py-0.5 text-xs font-medium text-primary"
        >
          {tag}
          <button
            type="button"
            className="rounded-full p-0.5 hover:bg-primary/20"
            aria-label={`Remove ${tag}`}
            onClick={() => onChange(tags.filter((x) => x !== tag))}
          >
            <X className="size-3" />
          </button>
        </span>
      ))}
      <input
        id={id}
        type="text"
        value={draft}
        disabled={disabled}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={onKeyDown}
        onBlur={() => draft.trim() && addTag(draft)}
        placeholder={tags.length === 0 ? placeholder : undefined}
        className="min-w-[120px] flex-1 bg-transparent text-sm outline-none placeholder:text-dark-light"
      />
    </div>
  );
}
