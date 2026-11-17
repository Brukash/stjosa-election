import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // One ramp for the whole app: the public surface reads the role names
        // (paper/surface/forest/ochre/rule/clay), admin screens still use the
        // older names (ink, green, greenlight) mapped to the same values.
        ink: "#16241C",
        inklight: "#24382B",
        green: "#0E3B2A",
        greenlight: "#184C36",
        paper: "#F4EFE3",
        surface: "#FFFCF5",
        forest: "#0E3B2A",
        ochre: "#B0731F",
        rule: "#DAD2C0",
        clay: "#8C3B2E",
      },
      fontFamily: {
        display: ["var(--font-display)", "Georgia", "serif"],
        body: ["var(--font-body)", "'Segoe UI'", "system-ui", "sans-serif"],
        mono: ["'Cascadia Mono'", "Consolas", "ui-monospace", "monospace"],
      },
      maxWidth: {
        measure: "62ch",
      },
      boxShadow: {
        card: "0 1px 0 rgba(22,36,28,0.04), 0 12px 28px -18px rgba(22,36,28,0.35)",
        ballot: "0 1px 0 rgba(22,36,28,0.05), 0 24px 48px -32px rgba(22,36,28,0.55)",
      },
      letterSpacing: {
        eyebrow: "0.18em",
      },
      opacity: {
        8: "0.08",
        12: "0.12",
        15: "0.15",
        35: "0.35",
        45: "0.45",
        55: "0.55",
        65: "0.65",
        85: "0.85",
      },
    },
  },
  plugins: [],
};

export default config;
