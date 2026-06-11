import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// In dev, proxy /api to the FastAPI backend so the frontend talks to one origin.
// In the Docker build, the backend serves the built assets directly (no CDN).
// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
  build: {
    outDir: 'dist',
  },
})
