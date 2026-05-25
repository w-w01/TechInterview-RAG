"use client";

import { useTranslations } from "next-intl";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { DIFFICULTIES, type Difficulty } from "@/lib/types";
import { cn } from "@/lib/utils";

const triggerClass = cn(
  "h-11 w-full rounded-xl border-border/80 bg-background px-4 text-sm font-medium text-dark shadow-xs",
  "transition-[border-color,box-shadow] duration-200",
  "hover:border-primary/45",
  "data-[popup-open]:border-primary data-[popup-open]:ring-[3px] data-[popup-open]:ring-primary/20",
);

const contentClass = cn(
  "rounded-xl border border-border/90 bg-popover p-1.5",
  "shadow-[0_16px_48px_rgb(26_32_44/0.14)] ring-1 ring-border/60",
);

const itemClass = cn(
  "cursor-pointer rounded-lg py-2.5 pl-3 pr-9 text-sm font-medium text-dark-muted",
  "outline-none transition-colors duration-150",
  "data-[highlighted]:bg-primary/10 data-[highlighted]:text-primary",
  "data-[selected]:bg-primary/10 data-[selected]:text-primary",
  "[&_svg]:text-primary",
);

type Props = {
  id?: string;
  value: Difficulty;
  onChange: (value: Difficulty) => void;
  disabled?: boolean;
};

export function DifficultySelect({ id, value, onChange, disabled }: Props) {
  const t = useTranslations("session");

  const labelOf = (d: Difficulty) =>
    t(`difficultyOption_${d}` as "difficultyOption_beginner");

  const items = DIFFICULTIES.map((d) => ({
    value: d,
    label: labelOf(d),
  }));

  return (
    <Select
      value={value}
      onValueChange={(v) => {
        if (v) onChange(v as Difficulty);
      }}
      disabled={disabled}
      items={items}
    >
      <SelectTrigger id={id} className={triggerClass}>
        <SelectValue />
      </SelectTrigger>
      <SelectContent className={contentClass} sideOffset={8} align="start">
        {DIFFICULTIES.map((d) => (
          <SelectItem key={d} value={d} className={itemClass}>
            {labelOf(d)}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
