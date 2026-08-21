import { NextResponse, type NextRequest } from "next/server";

import { safeReturnTo } from "@/lib/auth/return-to";

export function proxy(request: NextRequest) {
  if (request.cookies.has("stytch_session")) {
    return NextResponse.next();
  }

  const returnTo = safeReturnTo(`${request.nextUrl.pathname}${request.nextUrl.search}`);
  const signIn = new URL("/sign-in", request.url);
  signIn.searchParams.set("reason", "AUTHENTICATION_REQUIRED");
  signIn.searchParams.set("returnTo", returnTo);
  return NextResponse.redirect(signIn);
}

export const config = {
  matcher: ["/((?!sign-in|authenticate|api/auth|_next/static|_next/image|favicon.ico).*)"],
};
