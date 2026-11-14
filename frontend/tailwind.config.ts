import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#0B3D24",
        inklight: "#155233",
        green: "#12703C",
        greenlight: "#0E5C31",
        leaf: "#1B8A4B",
        cream: "#FAF8EC",
        gold: "#E7D21C",
        line: "#DCE5D8",
      },
      fontFamily: {
        display: ["Georgia", "Cambria", "serif"],
        body: ["'Segoe UI'", "system-ui", "sans-serif"],
        mono: ["'Cascadia Mono'", "Consolas", "monospace"],
      },
      boxShadow: {
        card: "0 1px 2px rgba(14,33,64,0.06), 0 8px 24px rgba(14,33,64,0.05)",
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
