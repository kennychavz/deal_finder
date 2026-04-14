/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        card: "hsl(var(--card))",
        primary: "hsl(var(--primary))",
        secondary: "hsl(var(--secondary))",
        border: "hsl(var(--border))",
        pos: "hsl(var(--pos))",
        neg: "hsl(var(--neg))",
        warn: "hsl(var(--warn))",
        info: "hsl(var(--info))",
        grid: "hsl(var(--grid))",
        "muted-foreground": "hsl(var(--muted-foreground))",
      },
    },
  },
  plugins: [],
}
