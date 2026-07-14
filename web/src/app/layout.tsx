/**
 * Root layout — loads the technical type system and mounts the auth gate.
 * Author: gurvinny
 */
import type { Metadata } from "next";
import { Chakra_Petch, IBM_Plex_Sans, IBM_Plex_Mono } from "next/font/google";
import "./globals.css";
import { AuthGate } from "@/components/AuthGate";
import { ThemeProvider, themeBootstrap } from "@/components/ThemeProvider";
import { Starfield } from "@/components/viz/Starfield";

const chakra = Chakra_Petch({
  weight: ["400", "500", "600", "700"],
  subsets: ["latin"],
  variable: "--font-chakra",
});
const plexSans = IBM_Plex_Sans({
  weight: ["400", "500", "600"],
  subsets: ["latin"],
  variable: "--font-plex-sans",
});
const plexMono = IBM_Plex_Mono({
  weight: ["400", "500", "600"],
  subsets: ["latin"],
  variable: "--font-plex-mono",
});

export const metadata: Metadata = {
  title: "SPECTRE — WiFi Threat Sensor",
  description:
    "Signal Processing & Electromagnetic Threat Reconnaissance Engine",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html
      lang="en"
      suppressHydrationWarning
      className={`${chakra.variable} ${plexSans.variable} ${plexMono.variable}`}
    >
      <head>
        {/* Apply the saved skin before first paint so there's no flash. */}
        <script dangerouslySetInnerHTML={{ __html: themeBootstrap }} />
      </head>
      <body>
        <ThemeProvider>
          <Starfield />
          <AuthGate>{children}</AuthGate>
        </ThemeProvider>
      </body>
    </html>
  );
}
