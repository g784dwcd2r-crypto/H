import { redirect } from "next/navigation";
export const dynamic = "force-dynamic";
/** Preserve old company-search links while using the shared, explicitly indexed search. */
export default async function CompanySearch({ params, searchParams }: { params: Promise<{ cik: string }>; searchParams: Promise<{ q?: string }> }) {
  const { cik } = await params;
  const { q } = await searchParams;
  const query = new URLSearchParams({ cik });
  if (q) query.set("q", q);
  redirect(`/research?${query}`);
}
