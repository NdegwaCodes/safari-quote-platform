import type { Config } from "tailwindcss";
import acacia from "@acacia/brand/tailwind-preset";

const config: Config = {
  presets: [acacia],
  content: ["./src/**/*.{ts,tsx}"],
};

export default config;
