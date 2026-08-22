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
  const allowLocalE2EContext =
    process.env.NODE_ENV !== "production" &&
    process.env.PRIVEXA_E2E_AUTH_BYPASS === "true";
  return (
    <html lang="en">
      <body>
        <StytchProvider bypassForLocalE2E={allowLocalE2EContext}>{children}</StytchProvider>
      </body>
    </html>
  );
}
