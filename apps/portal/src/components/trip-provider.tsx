"use client";

import { createContext, useContext, useEffect, useState } from "react";
import { Refused } from "@/components/refused";
import type { ApiError, Trip } from "@/lib/types";


type State =
  | { kind: "opening" }
  | { kind: "open"; trip: Trip }
  | { kind: "refused"; error: ApiError };

const REFUSED_FALLBACK: ApiError = {
  code: "PORTAL_UNAVAILABLE",
  message:
    "Your trip could not be loaded just now. Please try again in a moment -- " +
    "nothing about your booking has changed.",
};

let opening: Promise<State> | null = null;

async function read(res: Response): Promise<State> {
  const text = await res.text();
  const data = text ? JSON.parse(text) : null;
  if (res.ok && data) return { kind: "open", trip: data as Trip };
  const error = (data?.error ?? REFUSED_FALLBACK) as ApiError;
  return { kind: "refused", error };
}

async function begin(): Promise<State> {
  const token = window.location.hash.replace(/^#/, "").trim();

  if (token) {
    window.history.replaceState(
      null,
      "",
      `${window.location.pathname}${window.location.search}`,
    );
    return read(
      await fetch("/api/session", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token }),
      }),
    );
  }

  return read(await fetch("/api/portal/trip"));
}

function open(): Promise<State> {
  if (!opening) {
    opening = begin().catch(
      (): State => ({ kind: "refused", error: REFUSED_FALLBACK }),
    );
  }
  return opening;
}

const Ctx = createContext<Trip | null>(null);

export function useTrip(): Trip {
  const trip = useContext(Ctx);
  if (!trip) throw new Error("useTrip outside a TripProvider");
  return trip;
}

export function TripProvider({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<State>({ kind: "opening" });

  useEffect(() => {
    let live = true;
    open().then((next) => {
      if (live) setState(next);
    });
    return () => {
      live = false;
    };
  }, []);

  if (state.kind === "opening") {
    return (
      <main className="grid min-h-dvh place-items-center px-6">
        <p className="text-sm text-ink-soft">Opening your trip...</p>
      </main>
    );
  }
  if (state.kind === "refused") return <Refused error={state.error} />;

  return <Ctx.Provider value={state.trip}>{children}</Ctx.Provider>;
}
