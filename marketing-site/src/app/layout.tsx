import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import { Toaster } from "sonner";

const inter = Inter({ subsets: ["latin"] });

export const metadata: Metadata = {
  title: "AI Forecasting - Advanced Stock Prediction Platform",
  description: "Transform your investment strategy with AI-powered stock forecasting. Accurate predictions, real-time insights, and proven results.",
  keywords: "AI forecasting, stock prediction, machine learning, investment, trading, financial analytics",
  authors: [{ name: "AI Forecasting Team" }],
  openGraph: {
    title: "AI Forecasting - Advanced Stock Prediction Platform",
    description: "Transform your investment strategy with AI-powered stock forecasting. Accurate predictions, real-time insights, and proven results.",
    type: "website",
    url: "https://aiforecasting.com",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className={inter.className}>
        {children}
        <Toaster />
      </body>
    </html>
  );
}
