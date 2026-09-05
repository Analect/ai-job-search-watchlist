export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        surface: "var(--surface)",
        "border-subtle": "var(--border)",
        ink: "var(--text)",
        muted: "var(--muted)",
        accent: "var(--accent)",
        danger: "var(--danger)",
        ok: "var(--ok)",
      },
      borderRadius: { card: "12px" },
      maxWidth: { app: "1080px" },
    },
  },
  plugins: [],
};
