import type { Metadata } from "next";

import { AuthenticationExperience } from "@/components/auth/authentication-experience";

export const metadata: Metadata = { title: "Sign in" };

type Props = {
  searchParams: Promise<{ reason?: string; returnTo?: string; signedOut?: string }>;
};

export default async function SignInPage({ searchParams }: Props) {
  const { reason, returnTo, signedOut } = await searchParams;
  return (
    <AuthenticationExperience
      reason={reason}
      returnTo={returnTo}
      signedOut={signedOut === "1"}
    />
  );
}
