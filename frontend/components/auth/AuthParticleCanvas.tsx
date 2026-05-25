"use client";

import { useEffect, useRef } from "react";

type Particle = {
  x: number;
  y: number;
  vx: number;
  vy: number;
  r: number;
  alpha: number;
};

type Pointer = { x: number; y: number; active: boolean };
type ClickRipple = { x: number; y: number; t: number; power: number };

const PARTICLE_COUNT = 200;
const CONNECT_DIST = 120;
/** 飞出视口多远后从对应边外缘重生 */
const OFFSCREEN_MARGIN = 200;

type Edge = "top" | "right" | "bottom" | "left";

/** 全屏交互粒子：四边均可飞出，无边缘反弹 */
export function AuthParticleCanvas() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const particlesRef = useRef<Particle[]>([]);
  const pointerRef = useRef<Pointer>({ x: -9999, y: -9999, active: false });
  const ripplesRef = useRef<ClickRipple[]>([]);
  const scrollRef = useRef(0);
  const sizeRef = useRef({ w: 0, h: 0 });
  const rafRef = useRef(0);
  const dprRef = useRef(1);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const root = canvas.closest(".auth-page") as HTMLElement | null;

    const reducedMotion = window.matchMedia(
      "(prefers-reduced-motion: reduce)",
    ).matches;

    const particleVisual = (): Pick<Particle, "r" | "alpha"> => ({
      r: 1 + Math.random() * 2.2,
      alpha: 0.04 + Math.random() * 0.08,
    });

    /** 视口内均匀分布 */
    const spawnInside = (w: number, h: number): Particle => ({
      x: Math.random() * w,
      y: Math.random() * h,
      vx: (Math.random() - 0.5) * 0.45,
      vy: (Math.random() - 0.5) * 0.45,
      ...particleVisual(),
    });

    /** 从指定边外侧飞入（也可随机选边） */
    const spawnFromEdge = (
      w: number,
      h: number,
      edge?: Edge,
    ): Particle => {
      const e =
        edge ??
        (["top", "right", "bottom", "left"] as const)[
          Math.floor(Math.random() * 4)
        ];
      const gap = 24 + Math.random() * 80;
      const speed = 0.22 + Math.random() * 0.38;
      const tangential = (Math.random() - 0.5) * 0.35;
      const base = particleVisual();

      switch (e) {
        case "top":
          return {
            x: Math.random() * w,
            y: -gap,
            vx: tangential,
            vy: speed,
            ...base,
          };
        case "bottom":
          return {
            x: Math.random() * w,
            y: h + gap,
            vx: tangential,
            vy: -speed,
            ...base,
          };
        case "left":
          return {
            x: -gap,
            y: Math.random() * h,
            vx: speed,
            vy: tangential,
            ...base,
          };
        case "right":
          return {
            x: w + gap,
            y: Math.random() * h,
            vx: -speed,
            vy: tangential,
            ...base,
          };
      }
    };

    const initParticles = (w: number, h: number) => {
      particlesRef.current = Array.from({ length: PARTICLE_COUNT }, (_, i) => {
        // 约一半在屏内，一半从四边流入，避免只往右侧堆积
        if (i % 2 === 0) return spawnInside(w, h);
        return spawnFromEdge(w, h);
      });
    };

    const respawnIfFar = (p: Particle, w: number, h: number) => {
      if (p.x < -OFFSCREEN_MARGIN) {
        Object.assign(p, spawnFromEdge(w, h, "left"));
        return;
      }
      if (p.x > w + OFFSCREEN_MARGIN) {
        Object.assign(p, spawnFromEdge(w, h, "right"));
        return;
      }
      if (p.y < -OFFSCREEN_MARGIN) {
        Object.assign(p, spawnFromEdge(w, h, "top"));
        return;
      }
      if (p.y > h + OFFSCREEN_MARGIN) {
        Object.assign(p, spawnFromEdge(w, h, "bottom"));
      }
    };

    const resize = () => {
      const parent = root ?? canvas.parentElement;
      if (!parent) return;
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      dprRef.current = dpr;
      const w = parent.clientWidth;
      const h = parent.clientHeight;
      if (w < 2 || h < 2) return;

      canvas.width = Math.floor(w * dpr);
      canvas.height = Math.floor(h * dpr);
      canvas.style.width = `${w}px`;
      canvas.style.height = `${h}px`;

      const sizeChanged =
        sizeRef.current.w !== w || sizeRef.current.h !== h;
      const needsSpawn = particlesRef.current.length === 0;
      if (sizeChanged || needsSpawn) {
        initParticles(w, h);
        sizeRef.current = { w, h };
      }
    };

    const onPointerMove = (e: PointerEvent) => {
      const rect = canvas.getBoundingClientRect();
      pointerRef.current = {
        x: e.clientX - rect.left,
        y: e.clientY - rect.top,
        active: true,
      };
    };

    const onPointerLeave = () => {
      pointerRef.current.active = false;
    };

    const onPointerDown = (e: PointerEvent) => {
      const rect = canvas.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const y = e.clientY - rect.top;
      ripplesRef.current.push({ x, y, t: 0, power: 1 });
      if (ripplesRef.current.length > 6) ripplesRef.current.shift();
      particlesRef.current.forEach((p) => {
        const dx = p.x - x;
        const dy = p.y - y;
        const dist = Math.hypot(dx, dy) || 1;
        p.vx += (dx / dist) * (8 / dist);
        p.vy += (dy / dist) * (8 / dist);
      });
    };

    const onWheel = (e: WheelEvent) => {
      if (!root?.contains(e.target as Node)) return;
      e.preventDefault();
      scrollRef.current += e.deltaY * 0.002;
      const w = canvas.clientWidth;
      const h = canvas.clientHeight;
      const cx = w / 2;
      const cy = h / 2;
      particlesRef.current.forEach((p) => {
        const dx = p.x - cx;
        const dy = p.y - cy;
        const dist = Math.hypot(dx, dy) || 1;
        p.vx += (-dy / dist) * e.deltaY * 0.004;
        p.vy += (dx / dist) * e.deltaY * 0.004;
      });
    };

    canvas.addEventListener("pointermove", onPointerMove);
    canvas.addEventListener("pointerleave", onPointerLeave);
    canvas.addEventListener("pointerdown", onPointerDown);
    canvas.addEventListener("wheel", onWheel, { passive: false });

    const draw = () => {
      const w = canvas.clientWidth;
      const h = canvas.clientHeight;
      const dpr = dprRef.current;

      if (w < 2 || h < 2 || !particlesRef.current.length) {
        rafRef.current = requestAnimationFrame(draw);
        return;
      }

      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

      const ptr = pointerRef.current;
      const scrollAngle = scrollRef.current;

      if (!reducedMotion) {
        ripplesRef.current = ripplesRef.current
          .map((r) => ({ ...r, t: r.t + 1 }))
          .filter((r) => r.t < 90);

        for (const p of particlesRef.current) {
          if (ptr.active) {
            const dx = ptr.x - p.x;
            const dy = ptr.y - p.y;
            const dist = Math.hypot(dx, dy);
            if (dist < 200 && dist > 1) {
              const pull = (200 - dist) / 200;
              p.vx += (dx / dist) * pull * 0.05;
              p.vy += (dy / dist) * pull * 0.05;
            }
            if (dist < 52) {
              const push = (52 - dist) / 52;
              p.vx -= (dx / dist) * push * 0.14;
              p.vy -= (dy / dist) * push * 0.14;
            }
          }

          p.vx += Math.sin(p.y * 0.007 + scrollAngle) * 0.01;
          p.vy += Math.cos(p.x * 0.007 + scrollAngle) * 0.01;

          for (const r of ripplesRef.current) {
            const dx = p.x - r.x;
            const dy = p.y - r.y;
            const dist = Math.hypot(dx, dy);
            const wave = Math.max(0, 1 - Math.abs(dist - r.t * 2.2) / 90);
            if (wave > 0) {
              p.vx += (dx / (dist || 1)) * wave * 0.09 * r.power;
              p.vy += (dy / (dist || 1)) * wave * 0.09 * r.power;
            }
          }

          p.vx *= 0.984;
          p.vy *= 0.984;
          p.x += p.vx;
          p.y += p.vy;

          respawnIfFar(p, w, h);
        }

        const pts = particlesRef.current;
        for (let i = 0; i < pts.length; i++) {
          for (let j = i + 1; j < pts.length; j++) {
            const dx = pts[i].x - pts[j].x;
            const dy = pts[i].y - pts[j].y;
            const dist = Math.hypot(dx, dy);
            if (dist < CONNECT_DIST) {
              const a = (1 - dist / CONNECT_DIST) * 0.06;
              ctx.beginPath();
              ctx.moveTo(pts[i].x, pts[i].y);
              ctx.lineTo(pts[j].x, pts[j].y);
              ctx.strokeStyle = `rgba(255, 255, 255, ${a})`;
              ctx.lineWidth = 0.6;
              ctx.stroke();
            }
          }
        }

        if (ptr.active) {
          const g = ctx.createRadialGradient(
            ptr.x,
            ptr.y,
            0,
            ptr.x,
            ptr.y,
            160,
          );
          g.addColorStop(0, "rgba(0, 242, 254, 0.12)");
          g.addColorStop(1, "transparent");
          ctx.fillStyle = g;
          ctx.fillRect(ptr.x - 160, ptr.y - 160, 320, 320);
        }

        for (const r of ripplesRef.current) {
          ctx.beginPath();
          ctx.arc(r.x, r.y, r.t * 2.5, 0, Math.PI * 2);
          ctx.strokeStyle = `rgba(0, 242, 254, ${Math.max(0, 0.35 - r.t / 90)})`;
          ctx.lineWidth = 1;
          ctx.stroke();
        }
      }

      for (const p of particlesRef.current) {
        const boost = ptr.active
          ? Math.max(0, 1 - Math.hypot(ptr.x - p.x, ptr.y - p.y) / 180) * 0.06
          : 0;
        const a = Math.min(0.2, p.alpha + boost);
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.r + boost * 0.4, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(255, 255, 255, ${a})`;
        ctx.fill();
      }

      rafRef.current = requestAnimationFrame(draw);
    };

    resize();
    const observeTarget = root ?? canvas.parentElement!;
    const ro = new ResizeObserver(resize);
    ro.observe(observeTarget);
    const layoutKick = requestAnimationFrame(() => {
      resize();
      requestAnimationFrame(resize);
    });
    rafRef.current = requestAnimationFrame(draw);

    return () => {
      cancelAnimationFrame(layoutKick);
      cancelAnimationFrame(rafRef.current);
      ro.disconnect();
      canvas.removeEventListener("pointermove", onPointerMove);
      canvas.removeEventListener("pointerleave", onPointerLeave);
      canvas.removeEventListener("pointerdown", onPointerDown);
      canvas.removeEventListener("wheel", onWheel);
    };
  }, []);

  return (
    <canvas
      ref={canvasRef}
      className="auth-particle-canvas pointer-events-auto absolute inset-0 z-[2] size-full cursor-crosshair"
      aria-hidden
    />
  );
}
