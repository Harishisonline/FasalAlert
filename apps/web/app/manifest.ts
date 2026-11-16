import type { MetadataRoute } from 'next';

/** PWA manifest (design.md 5.3). */
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: 'FasalAlert',
    short_name: 'FasalAlert',
    description: 'Frost, heat, price and route decisions for your field in Maharashtra.',
    start_url: '/?source=pwa', // proxy.ts opens Home when signed in, the landing page otherwise
    scope: '/',
    display: 'standalone',
    orientation: 'portrait',
    background_color: '#f7f8f6',
    theme_color: '#0b5c2e',
    lang: 'mr',
    icons: [
      { src: '/icons/icon-192.png', sizes: '192x192', type: 'image/png', purpose: 'any' },
      { src: '/icons/icon-512.png', sizes: '512x512', type: 'image/png', purpose: 'any' },
      { src: '/icons/icon-maskable-512.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
      { src: '/icons/icon.svg', sizes: 'any', type: 'image/svg+xml', purpose: 'any' },
    ],
  };
}
