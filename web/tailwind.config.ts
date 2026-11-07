import type { Config } from "tailwindcss";

// The only colours the UI may use (DESIGN.md §2). A check script fails the build
// if a hex colour appears anywhere else under web/.
const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        canvas: "#f5f6f8",
        surface: "#ffffff",
        ink: "#14161b",
        muted: "#5b6472",
        hairline: "#e6e8ec",
        fill: "#eef0f3",
        rose: {
          DEFAULT: "#e11d48",
          hover: "#be123c",
          tint: "#fff1f3",
          line: "#fbcfd8",
        },
      },
      fontFamily: {
        display: ["var(--font-hanken)", "system-ui", "sans-serif"],
        sans: ["var(--font-inter)", "system-ui", "sans-serif"],
        mono: ["var(--font-jetbrains)", "ui-monospace", "monospace"],
      },
      boxShadow: {
        card: "0 1px 2px rgba(20,22,27,0.04), 0 4px 12px rgba(20,22,27,0.04)",
      },
      letterSpacing: {
        eyebrow: "0.06em",
      },
    },
  },
  plugins: [],
};

export default config;
