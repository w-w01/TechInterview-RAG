"use client";

import { useEffect, useState } from "react";
import { useReducedMotion } from "framer-motion";

type Props = {
  value: number;
  className?: string;
};

export function ScoreDisplay({ value, className }: Props) {
  const reduceMotion = useReducedMotion();
  const [display, setDisplay] = useState(reduceMotion ? value : 0);

  useEffect(() => {
    if (reduceMotion) {
      setDisplay(value);
      return;
    }
    let frame = 0;
    const start = performance.now();
    const duration = 800;
    const tick = (now: number) => {
      const p = Math.min(1, (now - start) / duration);
      setDisplay(Math.round(value * p * 10) / 10);
      if (p < 1) {
        frame = requestAnimationFrame(tick);
      }
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [value, reduceMotion]);

  return (
    <span className={className}>
      {Number.isInteger(display) ? display : display.toFixed(1)}
    </span>
  );
}
