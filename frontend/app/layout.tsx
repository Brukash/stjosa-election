import type { Metadata, Viewport } from "next";
import localFont from "next/font/local";
import "./globals.css";

// Self-hosted (both SIL OFL, sources in ./fonts/README.md): the Google Fonts
// download can fail silently in a sandbox and swap in Georgia, so the files
// live in the repo instead.
// Instrument Serif for the masthead voice, Schibsted Grotesk for reading.
const display = localFont({
  src: [
    { path: "./fonts/instrument-serif-400.woff2", weight: "400", style: "normal" },
    { path: "./fonts/instrument-serif-400-italic.woff2", weight: "400", style: "italic" },
  ],
  variable: "--font-display",
  display: "swap",
  fallback: ["Georgia", "serif"],
});

const body = localFont({
  src: [
    { path: "./fonts/schibsted-grotesk-400-700.woff2", weight: "400 700", style: "normal" },
  ],
  variable: "--font-body",
  display: "swap",
  fallback: ["Segoe UI", "system-ui", "sans-serif"],
});

export const metadata: Metadata = {
  title: {
    default: "St. John's College Jos Alumni Election",
    template: "%s · SJC Jos Alumni Election",
  },
  description:
    "The official voting platform of the St. John's College Jos Alumni Association. Vote from anywhere, check that your ballot was recorded, and read the declared result.",
  applicationName: "SJC Jos Alumni Election",
  authors: [{ name: "St. John's College Jos Alumni Association" }],
  openGraph: {
    title: "St. John's College Jos Alumni Election",
    description:
      "Vote from anywhere, check that your ballot was recorded, and read the declared result.",
    type: "website",
  },
  robots: { index: false, follow: false },
};

export const viewport: Viewport = {
  themeColor: "#0E3B2A",
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${display.variable} ${body.variable}`}>
      <body>{children}</body>
    </html>
  );
}
