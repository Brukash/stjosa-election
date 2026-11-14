import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "St. John's College Jos Alumni Election",
  description:
    "Secure, end-to-end verifiable remote electronic voting for the St. John's College Jos Alumni Association.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
