export const SITE_URL = process.env.SITE_URL ?? "http://localhost:3002";

export const SITE_NAME = "Acacia Tours & Travel";

export const SITE_TAGLINE =
  "Tailor-made safaris and coast holidays in Kenya, arranged end to end.";

export const WHATSAPP_NUMBER = "254700000000";
export const WHATSAPP_URL = `https://wa.me/${WHATSAPP_NUMBER}?text=${encodeURIComponent(
  "Hello Acacia Tours, I would like to ask about a safari.",
)}`;

export const canonical = (path: string) => new URL(path, SITE_URL).toString();

export function imageSrc(url: string): string {
  return url.replace(/^\/api\/v1\/public\/images\//, "/img/");
}
