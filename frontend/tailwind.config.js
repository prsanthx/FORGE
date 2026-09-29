/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#f4f4f5",
        mute: "#a1a1aa",
        faint: "#71717a",
        accent: "#8ab4ff",
        ok: "#4ade80",
        bad: "#f87171",
        info: "#7dd3fc",
        panel: "#121214",
        elevated: "#18181b",
        line: "#2a2a2e",
      },
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "Segoe UI", "Helvetica Neue", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      boxShadow: {
        lift: "0 18px 50px -28px rgba(0,0,0,0.85)",
        ring: "0 0 0 4px rgba(138,180,255,0.12)",
      },
    },
  },
  plugins: [],
};
