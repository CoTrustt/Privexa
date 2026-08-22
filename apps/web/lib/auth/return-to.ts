const DEFAULT_RETURN_TO = "/";
export const RETURN_TO_COOKIE_NAME = "privexa_return_to";

export function safeReturnTo(candidate: string | null | undefined): string {
  if (!candidate || !candidate.startsWith("/") || candidate.startsWith("//")) {
    return DEFAULT_RETURN_TO;
  }

  try {
    const parsed = new URL(candidate, "https://privexa.invalid");
    if (parsed.origin !== "https://privexa.invalid") {
      return DEFAULT_RETURN_TO;
    }
    return `${parsed.pathname}${parsed.search}${parsed.hash}`;
  } catch {
    return DEFAULT_RETURN_TO;
  }
}

export function signInPath(returnTo: string | null | undefined): string {
  const destination = safeReturnTo(returnTo);
  return destination === DEFAULT_RETURN_TO
    ? "/sign-in"
    : `/sign-in?returnTo=${encodeURIComponent(destination)}`;
}

export function rememberReturnTo(destination: string): void {
  document.cookie = `${RETURN_TO_COOKIE_NAME}=${encodeURIComponent(safeReturnTo(destination))}; Path=/; Max-Age=600; SameSite=Lax`;
}

export function readRememberedReturnTo(): string {
  const cookie = document.cookie
    .split(";")
    .map((part) => part.trim())
    .find((part) => part.startsWith(`${RETURN_TO_COOKIE_NAME}=`));
  if (!cookie) return DEFAULT_RETURN_TO;

  try {
    return safeReturnTo(decodeURIComponent(cookie.slice(RETURN_TO_COOKIE_NAME.length + 1)));
  } catch {
    return DEFAULT_RETURN_TO;
  }
}

export function clearRememberedReturnTo(): void {
  document.cookie = `${RETURN_TO_COOKIE_NAME}=; Path=/; Max-Age=0; SameSite=Lax`;
}
