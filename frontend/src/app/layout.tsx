import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import Navigation from "../components/Navigation";
import { ToastProvider } from "../components/Toast";
import { AuthProvider } from "../lib/AuthContext";
import { PortfolioProvider } from "../lib/PortfolioContext";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Portfolio Tracker",
  description: "Real-time portfolio tracking, theme analysis, and P&L dashboard",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body
        className={`${geistSans.variable} ${geistMono.variable} antialiased bg-gray-900`}
      >
        <AuthProvider>
          <PortfolioProvider>
            <ToastProvider>
              <Navigation />
              {children}
            </ToastProvider>
          </PortfolioProvider>
        </AuthProvider>
      </body>
    </html>
  );
}
