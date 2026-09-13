import { NextRequest, NextResponse } from "next/server";
import { issueVisitor, verifyVisitor, VISITOR_COOKIE, VISITOR_HEADER, VISITOR_MAX_AGE } from "@/lib/gateway-identity";

export async function proxy(request: NextRequest) {
  const secret = process.env.FILINGS_API_KEY || "";
  const forwarded = new Headers(request.headers);
  // Never accept an identity chosen by the incoming HTTP caller.
  forwarded.delete(VISITOR_HEADER);
  let fresh: string | null = null;
  if (secret) {
    let token = request.cookies.get(VISITOR_COOKIE)?.value;
    let id = await verifyVisitor(token, secret);
    if (!id) {
      const issued = await issueVisitor(secret);
      id = issued.id; token = issued.token; fresh = token;
      request.cookies.set(VISITOR_COOKIE, token);
      // Make the first page's server requests use the same identity as subsequent browser requests.
      forwarded.set("cookie", request.headers.get("cookie") ?? "");
    }
    forwarded.set(VISITOR_HEADER, id);
  }
  const response = NextResponse.next({ request: { headers: forwarded } });
  if (fresh) response.cookies.set(VISITOR_COOKIE, fresh, { httpOnly: true, secure: request.nextUrl.protocol === "https:" || process.env.NODE_ENV === "production", sameSite: "lax", path: "/", maxAge: VISITOR_MAX_AGE });
  return response;
}
export const config = { matcher: ["/((?!_next/static|_next/image|favicon.ico|robots.txt|sitemap.xml).*)"] };
