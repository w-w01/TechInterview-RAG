const STORAGE_KEY = "im_auth_otp_deadline";
const DEFAULT_SECONDS = 60;

/** 读取验证码倒计时剩余秒数（跨刷新持久化） */
export function getOtpRemainingSeconds(): number {
  if (typeof window === "undefined") return 0;
  const raw = localStorage.getItem(STORAGE_KEY);
  if (!raw) return 0;
  const deadline = parseInt(raw, 10);
  if (Number.isNaN(deadline)) return 0;
  return Math.max(0, Math.ceil((deadline - Date.now()) / 1000));
}

/** 启动倒计时并写入 localStorage */
export function startOtpCountdown(seconds = DEFAULT_SECONDS): void {
  if (typeof window === "undefined") return;
  localStorage.setItem(
    STORAGE_KEY,
    String(Date.now() + seconds * 1000),
  );
}

export function clearOtpCountdown(): void {
  if (typeof window === "undefined") return;
  localStorage.removeItem(STORAGE_KEY);
}

export function isOtpCooldownActive(): boolean {
  return getOtpRemainingSeconds() > 0;
}
