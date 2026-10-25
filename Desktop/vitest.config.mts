import { defineConfig } from 'vitest/config'
import { resolve } from 'node:path'

export default defineConfig({
  resolve: { alias: { '@': resolve('src/renderer/src') } },
  test: { environment: 'happy-dom', include: ['tests/**/*.test.ts'] }
})
