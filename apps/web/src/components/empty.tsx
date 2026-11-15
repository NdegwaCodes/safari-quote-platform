import Link from "next/link";

export function Empty({ what }: { what: string }) {
  return (
    <div className="rounded-xl border border-hairline bg-cream-tint px-6 py-8 shadow-sm">
      <p className="text-[14px] leading-relaxed text-ink-soft">
        We are still putting {what} onto the site. In the meantime, tell us
        what you are looking for and a consultant will answer with real
        options.
      </p>
      <Link
        href="/enquire"
        className="mt-4 inline-block border-b border-gold pb-0.5 text-[13px] text-gold"
      >
        Tell us what you have in mind
      </Link>
    </div>
  );
}
