/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        base: "#080D18",
        side: "#0B1220",
        surface: "#111B2B",
        raised: "#162235",
        canvas: "#0C1422",
        line: "#263449",
        lineStrong: "#36475F",
        primary: { DEFAULT: "#6366F1", hover: "#7577F4", soft: "#6366F11F" },
        cyan: { DEFAULT: "#22D3EE", soft: "#22D3EE1A" },
        ai: { DEFAULT: "#8B5CF6", soft: "#8B5CF61F" },
        trigger: { DEFAULT: "#F59E0B", soft: "#F59E0B1F" },
        action: { DEFAULT: "#3B82F6", soft: "#3B82F61F" },
        success: { DEFAULT: "#22C55E", soft: "#22C55E1A" },
        warning: { DEFAULT: "#F59E0B", soft: "#F59E0B1A" },
        danger: { DEFAULT: "#EF4444", soft: "#EF44441A" },
        ink: "#F1F5F9",
        muted: "#94A3B8",
        faint: "#64748B",
      },
      fontFamily: {
        sans: ["Inter Variable", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "monospace"],
      },
      fontSize: { "2xs": ["11px", "15px"] },
      boxShadow: { panel: "0 8px 30px rgba(0,0,0,.35)", node: "0 2px 10px rgba(0,0,0,.35)" },
    },
  },
  plugins: [],
};
