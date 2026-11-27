import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Partner-Copilot | apoBank",
  description: "Demo-Arbeitsbereich für Partnerakten und Gespräche.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="de" className="h-full">
      <body className="h-full antialiased">{children}</body>
    </html>
  );
}
