import { NextRequest } from "next/server";
import { api } from "@/lib/server-api";

export async function POST(req: NextRequest) {
  const body = await req.json().catch(() => ({}));
  const r = await api.post("/auth/magic-link", { email: body.email });
  return Response.json(r.data, { status: r.status });
}
