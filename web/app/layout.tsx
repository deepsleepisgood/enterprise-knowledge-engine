import type { Metadata } from "next";
import { Hanken_Grotesk, Inter, JetBrains_Mono } from "next/font/google";

import { AppShell } from "@/components/shell/AppShell";
import { RoleProvider } from "@/components/shell/RoleContext";
import { SignalProvider } from "@/components/shell/Signals";
import { ToastProvider } from "@/components/ui/Primitives";

import "./globals.css";

const hanken = Hanken_Grotesk({
  subsets: ["latin"],
  weight: ["600", "700"],
  variable: "--font-hanken",
  display: "swap",
});
const inter = Inter({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-inter",
  display: "swap",
});
const jetbrains = JetBrains_Mono({
  subsets: ["latin"],
  weight: ["400", "500"],
  variable: "--font-jetbrains",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Knowledge Engine",
  description: "Cited answers from SOPs, client memos, desk instructions and expert transcripts.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${hanken.variable} ${inter.variable} ${jetbrains.variable}`}>
      <body>
        <RoleProvider>
          <SignalProvider>
            <ToastProvider>
              <AppShell>{children}</AppShell>
            </ToastProvider>
          </SignalProvider>
        </RoleProvider>
      </body>
    </html>
  );
}
