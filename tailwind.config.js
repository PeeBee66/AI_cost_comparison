/** @type {import('tailwindcss').Config} */
// Built at image-build time into app/static/tailwind.css so the dashboard has
// NO runtime dependency on the external Tailwind CDN (which can be blocked by
// DNS filtering on a LAN). All utility classes are literal strings in the
// Jinja templates, so the default content scan captures everything.
module.exports = {
  content: ['./app/templates/**/*.html'],
  theme: {
    extend: {
      colors: {
        brand: {
          50:  '#eef9ff',
          100: '#d9f0ff',
          500: '#3b82f6',
          600: '#2563eb',
          700: '#1d4ed8',
        },
      },
    },
  },
}
