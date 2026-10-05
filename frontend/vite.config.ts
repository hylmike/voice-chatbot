import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
  ],
  server: {
    port: 3000,
    proxy: {
      '/chat': {
        target: 'http://localhost:3100',
        changeOrigin: true,
      },
      '/health': {
        target: 'http://localhost:3100',
        changeOrigin: true,
      },
      '/ws': {
        target: 'ws://localhost:3100',
        ws: true,
      },
    },
  },
})
