/** @type {import('tailwindcss').Config} */
const channel = (name) => `rgb(var(--${name}) / <alpha-value>)`;

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: channel("ink"),
        mute: channel("mute"),
        faint: channel("faint"),
        accent: channel("accent"),
        ok: channel("ok"),
        bad: channel("bad"),
        info: channel("info"),
        panel: channel("panel"),
        elevated: channel("elevated"),
        line: channel("line"),
        sunken: channel("sunken"),
        canvas: channel("canvas"),
        sidebar: channel("sidebar"),
        onaccent: channel("onaccent"),
      },
      fontFamily: {
        sans: [
          "-apple-system",
          "BlinkMacSystemFont",
          "Segoe UI",
          "PingFang SC",
          "Helvetica Neue",
          "sans-serif",
        ],
        mono: ["JetBrains Mono", "ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      boxShadow: {
        lift: "0 12px 32px -24px rgb(var(--shadow) / 0.45)",
        ring: "0 0 0 3px rgb(var(--accent) / 0.18)",
      },
    },
  },
  plugins: [],
};
