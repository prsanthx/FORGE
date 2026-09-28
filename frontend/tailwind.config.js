/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#f3eee4",
        mute: "#a89880",
        brass: "#e2a84b",
        ok: "#8fbf7a",
        bad: "#e07a5f",
        info: "#7eb6d6",
        panel: "#1c1a15",
        line: "#3c3428",
      },
      fontFamily: {
        sans: ["Avenir Next", "Segoe UI", "Helvetica Neue", "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
        display: ["Iowan Old Style", "Palatino Linotype", "Palatino", "Georgia", "serif"],
      },
      boxShadow: {
        insetbrass: "inset 0 0 0 1px rgba(226,168,75,0.35)",
      },
    },
  },
  plugins: [],
};
