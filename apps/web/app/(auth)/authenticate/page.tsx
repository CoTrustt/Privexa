import type { Metadata } from "next";
import { cookies } from "next/headers";

import { AuthenticationExperience } from "@/components/auth/authentication-experience";
import { RETURN_TO_COOKIE_NAME, safeReturnTo } from "@/lib/auth/return-to";

export const metadata: Metadata = { title: "Completing sign-in" };

type Props = {
  searchParams: Promise<{ returnTo?: string }>;
};

export default async function AuthenticatePage({ searchParams }: Props) {
  const [{ returnTo }, cookieStore] = await Promise.all([searchParams, cookies()]);
  const rememberedReturnTo = cookieStore.get(RETURN_TO_COOKIE_NAME)?.value;
  let decodedRememberedReturnTo: string | undefined;
  if (rememberedReturnTo) {
    try {
      decodedRememberedReturnTo = decodeURIComponent(rememberedReturnTo);
    } catch {
      decodedRememberedReturnTo = undefined;
    }
  }

  return (
    <AuthenticationExperience
      callback
      returnTo={safeReturnTo(returnTo ?? decodedRememberedReturnTo)}
    />
  );
}
