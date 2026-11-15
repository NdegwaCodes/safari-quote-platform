import type { Metadata } from "next";
import "./globals.css";
import { body, display } from "@/lib/fonts";

export const metadata: Metadata = {
  title: "Your trip",
  robots: { index: false, follow: false },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className={`${display.variable} ${body.variable}`}>
      <body className="font-body">{children}</body>
    </html>
  );
}
