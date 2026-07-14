/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{vue,js,ts,jsx,tsx}",
  ],
  // fontFamily 真源在 src/styles/tokens.css 的 @theme 块，
  // 此处 theme.extend 留空避免冗余覆盖。
  theme: {
    extend: {},
  },
  plugins: [],
}
