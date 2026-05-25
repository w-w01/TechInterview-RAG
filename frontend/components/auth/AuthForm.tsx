"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";
import { motion } from "framer-motion";
import { Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { FloatingField } from "@/components/auth/FloatingField";
import { PasswordField } from "@/components/auth/PasswordField";
import {
  getOtpRemainingSeconds,
  isOtpCooldownActive,
  startOtpCountdown,
} from "@/lib/auth-otp-countdown";
import { cn } from "@/lib/utils";

type AuthMode = "login" | "register";
type AuthMethod = "password" | "code";

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

/** 可选表单项：高度展开/收起，避免 mount 时位移闪烁 */
const collapsibleField = (open: boolean) =>
  cn(
    "grid transition-[grid-template-rows,opacity] duration-300 ease-[cubic-bezier(0.22,1,0.36,1)]",
    open ? "grid-rows-[1fr] opacity-100" : "grid-rows-[0fr] opacity-0",
  );

export function AuthForm() {
  const t = useTranslations("auth");
  const locale = useLocale();
  const router = useRouter();
  const base = `/${locale}`;

  const [mode, setMode] = useState<AuthMode>("login");
  const [method, setMethod] = useState<AuthMethod>("password");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [code, setCode] = useState("");
  const [touched, setTouched] = useState<Record<string, boolean>>({});
  const [shakeKey, setShakeKey] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [otpSeconds, setOtpSeconds] = useState(0);

  const otpTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const syncOtpCountdown = useCallback(() => {
    const s = getOtpRemainingSeconds();
    setOtpSeconds(s);
    if (s === 0 && otpTimerRef.current) {
      clearInterval(otpTimerRef.current);
      otpTimerRef.current = null;
    }
  }, []);

  useEffect(() => {
    syncOtpCountdown();
    if (isOtpCooldownActive()) {
      otpTimerRef.current = setInterval(syncOtpCountdown, 500);
    }
    return () => {
      if (otpTimerRef.current) clearInterval(otpTimerRef.current);
    };
  }, [syncOtpCountdown]);

  const emailError =
    touched.email && !EMAIL_RE.test(email.trim())
      ? t("errorEmail")
      : undefined;
  const emailOk = touched.email && EMAIL_RE.test(email.trim());

  const passwordError =
    touched.password && password.length < 8
      ? t("errorPassword")
      : undefined;
  const passwordOk = touched.password && password.length >= 8;

  const confirmError =
    mode === "register" &&
    touched.confirm &&
    password !== confirmPassword
      ? t("errorConfirm")
      : undefined;

  const codeError =
    method === "code" && touched.code && code.trim().length < 4
      ? t("errorCode")
      : undefined;

  const triggerShake = (key: string) => {
    setShakeKey(key);
    window.setTimeout(() => setShakeKey(null), 480);
  };

  const requestOtp = () => {
    if (!EMAIL_RE.test(email.trim())) {
      setTouched((t) => ({ ...t, email: true }));
      triggerShake("email");
      return;
    }
    startOtpCountdown(60);
    setOtpSeconds(60);
    if (otpTimerRef.current) clearInterval(otpTimerRef.current);
    otpTimerRef.current = setInterval(syncOtpCountdown, 500);
  };

  const validate = (): boolean => {
    const next: Record<string, boolean> = {
      email: true,
      password: method === "password",
      confirm: mode === "register" && method === "password",
      code: method === "code",
    };
    setTouched((prev) => ({ ...prev, ...next }));

    if (!EMAIL_RE.test(email.trim())) {
      triggerShake("email");
      return false;
    }
    if (method === "password") {
      if (password.length < 8) {
        triggerShake("password");
        return false;
      }
      if (mode === "register" && password !== confirmPassword) {
        triggerShake("confirm");
        return false;
      }
    } else if (code.trim().length < 4) {
      triggerShake("code");
      return false;
    }
    return true;
  };

  const onSubmit = async (e?: React.FormEvent) => {
    e?.preventDefault();
    if (!validate()) return;
    setSubmitting(true);
    await new Promise((r) => setTimeout(r, 600));
    setSubmitting(false);
    router.push(`${base}/session`);
  };

  const switchMode = (next: AuthMode) => {
    setMode(next);
    setTouched({});
  };

  const switchMethod = (next: AuthMethod) => {
    setMethod(next);
    setTouched({});
  };

  return (
    <div className="auth-form mx-auto flex w-full max-w-[400px] flex-col px-2 py-5 sm:max-w-[420px] sm:px-4 sm:py-6">
      <Link
        href={base}
        className="mb-5 shrink-0 text-sm font-medium text-dark-muted transition-colors hover:text-primary"
      >
        ← {t("backHome")}
      </Link>

      <div className="mb-5 flex shrink-0 rounded-full border border-border bg-muted/40 p-1">
        {(["login", "register"] as const).map((m) => (
          <button
            key={m}
            type="button"
            onClick={() => switchMode(m)}
            className={cn(
              "relative flex-1 rounded-full py-2 text-sm font-medium transition-colors",
              mode === m ? "text-dark" : "text-dark-muted hover:text-dark",
            )}
          >
            {mode === m && (
              <motion.span
                layoutId="auth-mode-pill"
                className="absolute inset-0 rounded-full bg-background shadow-sm"
                transition={{ type: "spring", stiffness: 420, damping: 32 }}
              />
            )}
            <span className="relative z-10">
              {m === "login" ? t("tabLogin") : t("tabRegister")}
            </span>
          </button>
        ))}
      </div>

      <motion.h1
        key={mode}
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ duration: 0.2 }}
        className="text-2xl font-semibold tracking-tight text-dark"
      >
        {mode === "login" ? t("titleLogin") : t("titleRegister")}
      </motion.h1>
      <p className="mt-2 text-sm text-dark-muted">{t("subtitle")}</p>

      <div className="mt-6 flex gap-2">
        {(["password", "code"] as const).map((m) => (
          <button
            key={m}
            type="button"
            onClick={() => switchMethod(m)}
            className={cn(
              "rounded-lg border px-3 py-1.5 text-xs font-medium transition-all",
              method === m
                ? "border-primary bg-primary/10 text-primary"
                : "border-border text-dark-muted hover:border-primary/40",
            )}
          >
            {m === "password" ? t("methodPassword") : t("methodCode")}
          </button>
        ))}
      </div>

      <form
        className="mt-6"
        onSubmit={(e) => void onSubmit(e)}
        noValidate
      >
        <div className="space-y-4">
          <FloatingField
            label={t("email")}
            type="email"
            name="email"
            autoComplete="username email"
            inputMode="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            onBlur={() => setTouched((t) => ({ ...t, email: true }))}
            error={emailError}
            success={emailOk}
            shake={shakeKey === "email"}
          />

          <div className={collapsibleField(method === "password")}>
            <div className="space-y-4 overflow-hidden">
              <PasswordField
                label={t("password")}
                name="password"
                autoComplete={
                  mode === "register" ? "new-password" : "current-password"
                }
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                onBlur={() => setTouched((t) => ({ ...t, password: true }))}
                onKeyDown={(e) => {
                  if (e.key === "Enter") void onSubmit();
                }}
                error={passwordError}
                success={passwordOk}
                shake={shakeKey === "password"}
                tabIndex={method === "password" ? 0 : -1}
                aria-hidden={method !== "password"}
              />
              <div className={collapsibleField(mode === "register")}>
                <div className="overflow-hidden">
                  <PasswordField
                    label={t("confirmPassword")}
                    name="confirmPassword"
                    autoComplete="new-password"
                    value={confirmPassword}
                    onChange={(e) => setConfirmPassword(e.target.value)}
                    onBlur={() =>
                      setTouched((t) => ({ ...t, confirm: true }))
                    }
                    error={confirmError}
                    shake={shakeKey === "confirm"}
                    tabIndex={mode === "register" ? 0 : -1}
                    aria-hidden={mode !== "register"}
                  />
                </div>
              </div>
            </div>
          </div>

          <div className={collapsibleField(method === "code")}>
            <div className="overflow-hidden">
              <div className="flex gap-2">
                <div className="min-w-0 flex-1">
                  <FloatingField
                    label={t("verifyCode")}
                    name="otp"
                    autoComplete="one-time-code"
                    inputMode="numeric"
                    value={code}
                    onChange={(e) => setCode(e.target.value)}
                    onBlur={() => setTouched((t) => ({ ...t, code: true }))}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") void onSubmit();
                    }}
                    error={codeError}
                    shake={shakeKey === "code"}
                    tabIndex={method === "code" ? 0 : -1}
                    aria-hidden={method !== "code"}
                  />
                </div>
                <Button
                  type="button"
                  variant="outline"
                  className="mt-1 h-[52px] shrink-0 rounded-xl px-4"
                  disabled={otpSeconds > 0 || method !== "code"}
                  onClick={requestOtp}
                  tabIndex={method === "code" ? 0 : -1}
                  aria-hidden={method !== "code"}
                >
                  {otpSeconds > 0
                    ? t("otpWait", { s: otpSeconds })
                    : t("otpSend")}
                </Button>
              </div>
            </div>
          </div>
        </div>

        <Button
          type="submit"
          className="mt-6 h-12 w-full rounded-xl text-base"
          disabled={submitting}
        >
          {submitting ? (
            <>
              <Loader2 className="size-4 animate-spin" />
              {t("submitting")}
            </>
          ) : mode === "login" ? (
            t("submitLogin")
          ) : (
            t("submitRegister")
          )}
        </Button>
      </form>

      <div className="relative my-8">
        <div className="absolute inset-0 flex items-center">
          <span className="w-full border-t border-border" />
        </div>
        <span className="auth-or-divider-chip relative mx-auto block w-fit px-3 text-xs text-dark-muted">
          {t("orContinue")}
        </span>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <Button type="button" variant="outline" className="h-11 rounded-xl">
          {t("oauthGoogle")}
        </Button>
        <Button type="button" variant="outline" className="h-11 rounded-xl">
          {t("oauthGithub")}
        </Button>
      </div>

      <p className="mt-6 shrink-0 pb-2 text-center text-xs text-dark-light">
        {t("termsHint")}
      </p>
    </div>
  );
}
