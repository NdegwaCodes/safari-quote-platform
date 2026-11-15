import { WORDMARK, WORDMARK_SUB } from "@/lib/brand";
import type { ApiError } from "@/lib/types";

const HEADINGS: Record<string, string> = {
  portal_link_expired: "This link has expired",
  portal_link_revoked: "This link has been withdrawn",
  portal_booking_cancelled: "This booking has been cancelled",
  portal_no_link: "Open your trip from your own link",
};

export function Refused({ error }: { error: ApiError }) {
  const heading = HEADINGS[error.code] ?? "This link does not open a trip";

  return (
    <main className="grid min-h-dvh place-items-center px-6 py-16">
      <div className="max-w-lg">
        <p className="text-[11px] uppercase tracking-eyebrow text-gold">
          {WORDMARK} {WORDMARK_SUB}
        </p>
        <h1 className="mt-4 font-display text-4xl leading-tight">{heading}</h1>
        <p className="mt-5 text-[15px] leading-relaxed text-ink-soft">
          {error.message}
        </p>
      </div>
    </main>
  );
}
