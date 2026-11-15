import localFont from "next/font/local";

export const display = localFont({
  src: [
    { path: "../fonts/cormorant-garamond-normal.woff2", style: "normal" },
    { path: "../fonts/cormorant-garamond-italic.woff2", style: "italic" },
  ],
  variable: "--font-display",
  display: "swap",
  fallback: ["Georgia", "serif"],
});

export const body = localFont({
  src: [{ path: "../fonts/libre-franklin-normal.woff2", style: "normal" }],
  variable: "--font-body",
  display: "swap",
  fallback: ["system-ui", "sans-serif"],
});
