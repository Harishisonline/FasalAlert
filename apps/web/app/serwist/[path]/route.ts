import { createSerwistRoute } from '@serwist/turbopack';

/** Serves the bundled service worker at /serwist/sw.js (Serwist Turbopack guide). */
const revision = `${Date.now()}`;

export const { dynamic, dynamicParams, revalidate, generateStaticParams, GET } = createSerwistRoute({
  swSrc: 'app/sw.ts',
  useNativeEsbuild: true,
  // Fonts are precached too, so Devanagari renders offline (design.md 20.5).
  globPatterns: ['.next/static/**/*.{js,css,html,ico,png,svg,webp,json,webmanifest,woff2}', 'public/**/*'],
  additionalPrecacheEntries: [
    { url: '/en/offline', revision },
    { url: '/mr/offline', revision },
    { url: '/hi/offline', revision },
  ],
});
