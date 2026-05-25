"use client";

import { forwardRef, useId, useState } from "react";
import { cn } from "@/lib/utils";

type Props = Omit<
  React.InputHTMLAttributes<HTMLInputElement>,
  "type"
> & {
  label: string;
  error?: string;
  success?: boolean;
  shake?: boolean;
};

/** 密码框：浮动标签 + 眨眼切换明文 */
export const PasswordField = forwardRef<HTMLInputElement, Props>(
  function PasswordField(
    { label, error, success, shake, className, id: idProp, ...props },
    ref,
  ) {
    const uid = useId();
    const id = idProp ?? uid;
    const [visible, setVisible] = useState(false);
    const [blink, setBlink] = useState(false);

    const toggle = () => {
      setVisible((v) => !v);
      setBlink(true);
      window.setTimeout(() => setBlink(false), 320);
    };

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
            type={visible ? "text" : "password"}
            placeholder=" "
            autoComplete={props.autoComplete ?? "current-password"}
            className={cn(
              "peer block w-full rounded-xl border px-4 pb-2.5 pt-6 pr-12 text-sm transition-[border-color,box-shadow] duration-200",
              className,
            )}
            aria-invalid={error ? true : undefined}
            {...props}
          />
          <label
            htmlFor={id}
            className="pointer-events-none absolute left-4 top-4 z-10 origin-left text-sm text-dark-muted transition-all duration-200 peer-focus:top-2 peer-focus:scale-[0.82] peer-focus:text-primary peer-[:not(:placeholder-shown)]:top-2 peer-[:not(:placeholder-shown)]:scale-[0.82]"
          >
            {label}
          </label>
          <button
            type="button"
            tabIndex={-1}
            onClick={toggle}
            className="absolute right-3 top-1/2 -translate-y-1/2 rounded-md p-1.5 text-dark-muted transition-colors hover:bg-muted hover:text-dark"
            aria-label={visible ? "Hide password" : "Show password"}
          >
            <svg
              width="22"
              height="22"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.75"
              className={cn(blink && "auth-eye-blink")}
              aria-hidden
            >
              {visible ? (
                <>
                  <path d="M3 3l18 18" />
                  <path d="M10.58 10.58a2 2 0 0 0 2.84 2.84" />
                  <path d="M9.88 5.09A10.94 10.94 0 0 1 12 5c7 0 10 7 10 7a18.45 18.45 0 0 1-2.16 3.19" />
                  <path d="M6.61 6.61A18.48 18.48 0 0 0 2 12s3 7 10 7a9.86 9.86 0 0 0 4.12-.88" />
                </>
              ) : (
                <>
                  <path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z" />
                  <circle cx="12" cy="12" r="3" className="auth-eye-pupil" />
                </>
              )}
            </svg>
          </button>
        </div>
        {error && (
          <p className="text-xs text-destructive" role="alert">
            {error}
          </p>
        )}
      </div>
    );
  },
);
