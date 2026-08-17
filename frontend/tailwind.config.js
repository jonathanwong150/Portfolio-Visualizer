/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: "#0b0e11",
        surface: "#151a21",
        surface2: "#1c232c",
        accent: "#00d09c",
        accentSoft: "#0a3d33",
        danger: "#f6465d",
        muted: "#8a94a6",
      },
    },
  },
  plugins: [],
};
