"use client";

import { useEffect } from "react";

export function Redirect({ to }: { to: string }) {
  useEffect(() => {
    window.location.replace(`${to}${window.location.hash}`);
  }, [to]);

  return (
    <main className="grid min-h-dvh place-items-center px-6 text-center">
      <p className="text-sm text-ink-soft">Opening your trip...</p>
    </main>
  );
}
