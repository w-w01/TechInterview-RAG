"use client";

import { AuthForm } from "@/components/auth/AuthForm";
import { AuthHeroCanvas } from "@/components/auth/AuthHeroCanvas";
import { AuthParticleCanvas } from "@/components/auth/AuthParticleCanvas";

export function AuthPageClient() {
  return (
    <div className="auth-page relative flex h-dvh max-h-dvh w-full overflow-hidden">
      <div className="auth-page-bg pointer-events-none absolute inset-0 z-0" aria-hidden />
      <div className="auth-page-glow pointer-events-none absolute inset-0 z-0" aria-hidden />
      <div className="auth-page-nebula pointer-events-none absolute inset-0 z-0" aria-hidden />
      {/* 全屏粒子层：可飞出左栏进入右侧背景；表单 z-[3] 拦截右侧点击 */}
      <AuthParticleCanvas />

      <aside className="pointer-events-none relative z-[3] hidden h-full min-h-0 w-[55%] shrink-0 overflow-hidden lg:block">
        <AuthHeroCanvas />
      </aside>

      <main className="auth-form-panel relative z-[3] flex h-full min-h-0 w-full shrink-0 overflow-hidden lg:w-[45%]">
        <div className="auth-form-scroll flex h-full min-h-0 w-full flex-col items-center overflow-y-auto overscroll-contain px-4 sm:px-6 lg:px-8">
          <AuthForm />
        </div>
      </main>
    </div>
  );
}
