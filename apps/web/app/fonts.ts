import { Inter, Noto_Sans_Devanagari } from 'next/font/google';

/**
 * Inter for Latin text and all numerals, Noto Sans Devanagari for Marathi and Hindi (PRD §14.1,
 * design.md 7.1, 7.2). next/font self-hosts both at build time: no runtime request to Google.
 * size-adjust starts at 100% for Noto (design.md 7.3) and is to be calibrated in visual QA.
 */
export const inter = Inter({ subsets: ['latin'], variable: '--font-inter', display: 'swap' });

export const notoDeva = Noto_Sans_Devanagari({ subsets: ['devanagari'], variable: '--font-noto-deva', display: 'swap' });
