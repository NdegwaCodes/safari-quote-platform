"use client";

import { Eyebrow } from "@/components/eyebrow";
import { useTrip } from "@/components/trip-provider";


export default function DocumentPage() {
  const trip = useTrip();

  return (
    <div className="space-y-6">
      <div className="no-print">
        <Eyebrow>Your proposal</Eyebrow>
        <h1 className="mt-3 font-display text-3xl">
          The document you accepted
        </h1>
        <p className="mt-3 max-w-xl text-[13px] leading-relaxed text-ink-soft">
          Exactly as it was sent to you, for {trip.reference}. It does not
          change when our prices do.
        </p>
      </div>

      <iframe
        src="/api/portal/document.html"
        title="Your proposal"
        className="h-[80vh] w-full border border-hairline bg-white"
      />

      <p className="no-print text-[12px] text-ink-soft">
        To keep a copy, use your browser&apos;s print or save-as-PDF from inside the
        document above.
      </p>
    </div>
  );
}
