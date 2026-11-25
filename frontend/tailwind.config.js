/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        navy: "#101D38",
        midnight: "#172B4D",
        royal: "#2864B4",
        steel: "#3979C9",
        "light-blue": "#83B5FF",
      },
    },
  },
  plugins: [],
};
