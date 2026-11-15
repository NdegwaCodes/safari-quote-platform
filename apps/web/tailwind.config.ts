import type { Config } from "tailwindcss";
import acacia from "@acacia/brand/tailwind-preset";

const config: Config = {
  presets: [acacia],
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        accent: {
          DEFAULT: "#1e4741",
          ink: "#14302b",
          soft: "#e3ede9",
        },
        gold: {
          bright: "#c99a3f",
          deep: "#a97f2f",
        },
      },
      borderRadius: {
        pill: "999px",
      },
    },
  },
};

export default config;
