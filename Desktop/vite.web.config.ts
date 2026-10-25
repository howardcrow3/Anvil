// Plain-browser build of the renderer (no Electron). Used for e2e tests and quick UI iteration:
//   npx vite build -c vite.web.config.ts && npx vite preview -c vite.web.config.ts
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'
import { resolve } from 'node:path'

export default defineConfig({
  root: resolve('src/renderer'),
  resolve: { alias: { '@': resolve('src/renderer/src') } },
  plugins: [react()],
  build: { outDir: resolve('dist-web'), emptyOutDir: true },
  preview: { host: '127.0.0.1', port: 4173, strictPort: true }
})
