export function money(amount: string | number, currency: string): string {
  const text = typeof amount === "number" ? amount.toFixed(2) : amount;
  const negative = text.trim().startsWith("-");
  const [whole = "0", cents] = text.replace("-", "").trim().split(".");
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  const trimmed = cents && /[1-9]/.test(cents) ? `.${cents.slice(0, 2)}` : "";
  return `${negative ? "-" : ""}${currency} ${grouped}${trimmed}`;
}
