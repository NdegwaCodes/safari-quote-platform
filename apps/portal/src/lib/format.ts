import { TZ } from "@/lib/tz";

const MONTHS = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

function parts(value: string | null | undefined) {
  if (!value) return null;
  const [y, m, d] = value.split("-").map(Number);
  if (!y || !m || !d || m < 1 || m > 12) return null;
  return { y, m, d };
}

export function longDate(value: string | null | undefined): string {
  const p = parts(value);
  if (!p) return value ?? "";
  return `${p.d} ${MONTHS[p.m - 1]} ${p.y}`;
}

export function shortDate(value: string | null | undefined): string {
  const p = parts(value);
  if (!p) return value ?? "";
  return `${p.d} ${MONTHS[p.m - 1]!.slice(0, 3)} ${p.y}`;
}

export function weekday(value: string | null | undefined): string {
  const p = parts(value);
  if (!p) return "";
  return new Date(Date.UTC(p.y, p.m - 1, p.d)).toLocaleDateString("en-GB", {
    weekday: "long",
    timeZone: "UTC",
  });
}

export function money(amount: string | number, currency: string): string {
  const text = typeof amount === "number" ? amount.toFixed(2) : amount;
  const negative = text.trim().startsWith("-");
  const [whole = "0", cents] = text.replace("-", "").trim().split(".");
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  const trimmed = cents && /[1-9]/.test(cents) ? `.${cents.slice(0, 2)}` : "";
  return `${negative ? "-" : ""}${currency} ${grouped}${trimmed}`;
}

export function today(): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: TZ }).format(new Date());
}

export function isPast(value: string): boolean {
  return value < today();
}

export function nights(count: number): string {
  return `${count} ${count === 1 ? "night" : "nights"}`;
}
