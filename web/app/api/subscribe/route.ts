import { NextRequest } from "next/server";
import { api } from "@/lib/api";

export async function POST(req: NextRequest) {
  const body = await req.json().catch(() => ({}));
  const r = await api.post("/subscriptions", { email: body.email, ciks: body.ciks });
  return Response.json(r.data, { status: r.status });
}
