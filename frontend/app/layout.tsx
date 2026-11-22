import type { Metadata, Viewport } from "next";
import localFont from "next/font/local";

import "./globals.css";
import { Providers } from "./providers";

/* The dealt pairing (taste-skill, software): Outfit for text and headings, DM Mono for figures and
 * codes. Self-hosted from the @fontsource packages: no font request leaves the browser. */
const outfit = localFont({
  src: "../node_modules/@fontsource-variable/outfit/files/outfit-latin-wght-normal.woff2",
  variable: "--font-outfit",
  weight: "100 900",
  display: "swap",
});
const dmMono = localFont({
  src: [
    { path: "../node_modules/@fontsource/dm-mono/files/dm-mono-latin-400-normal.woff2", weight: "400" },
    { path: "../node_modules/@fontsource/dm-mono/files/dm-mono-latin-500-normal.woff2", weight: "500" },
  ],
  variable: "--font-dm-mono",
  display: "swap",
});

export const metadata: Metadata = {
  title: { default: "AFTERMATH", template: "%s · AFTERMATH" },
  description:
    "Infrastructure resilience and disaster-recovery decision support. Simulation environment — not connected to live infrastructure.",
};

export const viewport: Viewport = { themeColor: "#0a0d14", colorScheme: "dark" };

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${outfit.variable} ${dmMono.variable} antialiased`}>
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
