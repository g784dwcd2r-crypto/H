import Link from "next/link";
import { notFound } from "next/navigation";
import CompanyNav from "@/components/CompanyNav";
import Reader from "@/components/Reader";
import { api, NotFound } from "@/lib/server-api";
import { fmtDate } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function FilingPage({
  params,
  searchParams,
}: {
  params: Promise<{ cik: string; accession: string }>;
  searchParams: Promise<{ file?: string }>;
}) {
  const { cik, accession } = await params;
  const { file } = await searchParams;
  let doc;
  let company;
  try {
    [doc, company] = await Promise.all([api.document(cik, accession, file), api.company(cik)]);
  } catch (e) {
    if (e instanceof NotFound) notFound();
    return (
      <>
        <p className="crumb"><Link href={`/companies/${cik}`}>← Back</Link></p>
        <div className="empty">
          <p>The document could not be fetched from EDGAR just now.</p>
          <p className="muted">
            Open it on sec.gov instead: <a href={`https://www.sec.gov/Archives/edgar/data/${cik}/${accession.replace(/-/g, "")}/${accession}-index.htm`} target="_blank" rel="noreferrer">filing index</a>.
          </p>
        </div>
      </>
    );
  }
  const name = company.company.name;
  const id = String(company.company.cik);
  const docs = await api.documents(id, 40).catch(() => null);
  const siblings = (docs?.documents[accession] ?? []).filter((d) => d.kind !== "support");
  const label = siblings.find((d) => d.filename === doc.filename)?.label ?? (doc.form.startsWith("8-K") ? "8-K" : doc.form);
  return (
    <>
      <p className="crumb"><Link href={`/companies/${id}`}>← {name}</Link></p>
      <div className="title-row">
        <div>
          <p className="eyebrow">{doc.form} · filed {fmtDate(doc.filed_date)}</p>
          <h1 className="h-doc">{label}</h1>
          <p className="meta">{name}</p>
        </div>
        <div className="actions">
          <a className="btn secondary" href={doc.source_url} target="_blank" rel="noreferrer">Open on sec.gov</a>
        </div>
      </div>
      <CompanyNav cik={id} />
      {siblings.length > 1 && (
        <p className="chips docs-nav">
          {siblings.map((d) => (
            <Link key={d.filename} href={`/companies/${id}/filings/${accession}?file=${encodeURIComponent(d.filename)}`} className={"chip link" + (d.filename === doc.filename ? " on" : "")}>
              {d.label}
            </Link>
          ))}
        </p>
      )}
      <Reader html={doc.html} toc={doc.toc} />
    </>
  );
}
