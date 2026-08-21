const problemCopy: Record<string, string> = {
  AUTHENTICATION_REQUIRED: "Sign in to continue.",
  AUTHENTICATION_FAILED: "We could not verify that sign-in. Request a new link and try again.",
  SESSION_EXPIRED: "Your session ended. Sign in again to continue.",
  MEMBER_NOT_PROVISIONED:
    "Your sign-in is valid, but your Privexa account is not ready. Contact your firm administrator.",
  MEMBERSHIP_INACTIVE:
    "Your firm membership is inactive. Contact your firm administrator if this is unexpected.",
  FIRM_INACTIVE: "This firm workspace is inactive. Contact your Privexa administrator.",
  AUTHENTICATION_SERVICE_UNAVAILABLE:
    "Sign-in verification is temporarily unavailable. Please try again in a moment.",
};

export function copyForProblem(code: string): string {
  return problemCopy[code] ?? "We could not complete sign-in. Please try again.";
}
