"use client";

import { forwardRef, useId } from "react";
import { cn } from "@/lib/utils";

type Props = React.InputHTMLAttributes<HTMLInputElement> & {
  label: string;
  error?: string;
  success?: boolean;
  shake?: boolean;
};

/** 浮动标签输入框：纯 CSS placeholder-shown + 校验态边框 */
export const FloatingField = forwardRef<HTMLInputElement, Props>(
  function FloatingField(
    { label, error, success, shake, className, id: idProp, ...props },
    ref,
  ) {
    const uid = useId();
    const id = idProp ?? uid;

    return (
      <div className="space-y-1">
        <div
          className={cn(
            "auth-float-field relative",
            error && "auth-float-field--error",
            success && "auth-float-field--success",
            shake && "auth-field-shake",
          )}
        >
          <input
            ref={ref}
            id={id}
            placeholder=" "
            className={cn(
              "peer block w-full rounded-xl border px-4 pb-2.5 pt-6 text-sm transition-[border-color,box-shadow] duration-200",
              className,
            )}
            aria-invalid={error ? true : undefined}
            aria-describedby={error ? `${id}-err` : undefined}
            {...props}
          />
          <label
            htmlFor={id}
            className="pointer-events-none absolute left-4 top-4 z-10 origin-left text-sm text-dark-muted transition-all duration-200 peer-focus:top-2 peer-focus:scale-[0.82] peer-focus:text-primary peer-[:not(:placeholder-shown)]:top-2 peer-[:not(:placeholder-shown)]:scale-[0.82]"
          >
            {label}
          </label>
        </div>
        {error && (
          <p id={`${id}-err`} className="text-xs text-destructive" role="alert">
            {error}
          </p>
        )}
      </div>
    );
  },
);
