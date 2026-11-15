import { fallbacks, palette } from "./index.js";

const preset = {
  theme: {
    extend: {
      colors: {
        paper: palette.paper,
        ink: { DEFAULT: palette.ink, soft: palette.inkSoft },
        panel: { DEFAULT: palette.panel, ink: palette.panelInk },
        gold: { DEFAULT: palette.gold, soft: palette.goldSoft },
        sea: { DEFAULT: palette.sea, tint: palette.seaTint },
        cream: { DEFAULT: palette.cream, tint: palette.creamTint },
        hairline: palette.hairline,
      },
      fontFamily: {
        display: ["var(--font-display)", ...fallbacks.display],
        body: ["var(--font-body)", ...fallbacks.body],
      },
      letterSpacing: {
        eyebrow: "0.14em",
      },
    },
  },
};

export default preset;
