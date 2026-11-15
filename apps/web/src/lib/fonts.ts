import { Plus_Jakarta_Sans } from "next/font/google";
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

export const body = Plus_Jakarta_Sans({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700", "800"],
  variable: "--font-body",
  display: "swap",
  fallback: ["system-ui", "sans-serif"],
});
