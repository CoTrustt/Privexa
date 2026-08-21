import type { Metadata } from "next";

import { StytchProvider } from "@/components/auth/stytch-provider";

import "./globals.css";

export const metadata: Metadata = {
  title: {
    default: "Privexa",
    template: "%s · Privexa",
  },
  description: "Privacy work, with the reasoning and evidence intact.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>
        <StytchProvider>{children}</StytchProvider>
      </body>
    </html>
  );
}
