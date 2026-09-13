import Link from "next/link";
import { compatibleHistory, ownershipSourceHref, ownershipValue, type OwnershipCardData, type OwnershipFlow, type OwnershipRow } from "@/lib/ownership";
import { safeSourceUrl } from "@/lib/research";
import styles from "./Ownership.module.css";

export function OwnershipFacts({ rows, kind }: { rows: OwnershipRow[]; kind: OwnershipFlow }) {
  const columns = kind === "insiders" ? ["owner_name", "transaction_date", "security_title", "transaction_code", "acquired_disposed", "shares", "price", "owned_after", "ownership_form", "is_derivative", "change_percent"] : kind === "institutions" ? ["issuer_name", "cusip", "security_title", "shares", "share_type", "put_call", "value_usd", "discretion"] : ["name", "cik", "shares", "percent"];
  const label: Record<string,string> = { owner_name: "Reporting person", transaction_date: "Transaction date", security_title: "Security", transaction_code: "Code", acquired_disposed: "Acquired / disposed", shares: "Shares / amount", price: "Price per unit", owned_after: "Reported after", ownership_form: "Direct / indirect", is_derivative: "Derivative", change_percent: "Change of prior holding (%)", issuer_name: "Issuer", cusip: "CUSIP", share_type: "Quantity type", put_call: "Put / call", value_usd: "Reported value (USD)", discretion: "Discretion", name: "Reporting person", cik: "CIK", percent: "Reported ownership (%)" };
  return <div className={styles.tableScroll} role="region" aria-label="Reported ownership facts" tabIndex={0}><table><thead><tr>{columns.map(column => <th key={column}>{label[column]}</th>)}</tr></thead><tbody>{rows.map((row,i) => <tr key={String(row.id || i)}>{columns.map(column => <td key={column}>{["cusip", "cik"].includes(column) ? String(row[column] ?? "Not reported") : ownershipValue(row[column])}</td>)}</tr>)}</tbody></table></div>;
}

export default function OwnershipCard({ card, cik, kind, returnTo, compact = false }: { card: OwnershipCardData; cik: string | number; kind: OwnershipFlow; returnTo?: string; compact?: boolean }) {
  const points = compatibleHistory(card.history);
  const values = points?.map(point => Number(point.value)) || [], min = Math.min(...values), max = Math.max(...values);
  const plot = points?.map((point,i) => `${8 + i / (points.length - 1) * 224},${max === min ? 32 : 56 - (Number(point.value) - min) / (max - min) * 48}`).join(" ");
  return <article className={styles.card} data-ownership-card={kind}>
    <div className={styles.cardTop}><div><p className={styles.role}>{card.role || (kind === "institutions" ? "Reporting investment manager" : kind === "events" ? "Reporting beneficial owner" : "Reporting person")}</p><h3>{card.name}</h3></div><span className={styles.date}>Filed {card.reported_date || "date unavailable"}</span></div>
    <p className={styles.action}>{card.summary}</p><p className={styles.note}>{kind === "institutions" ? "Position as of" : kind === "events" ? "Reported event date" : "Reported observation date"}: {card.date || "Not reported"}</p>
    {card.badges.length > 0 && <ul className={styles.badges} aria-label="Filing context">{card.badges.map((badge,i) => <li key={i}>{badge}</li>)}</ul>}
    <dl className={styles.metrics}>{card.metrics.map((metric,i) => <div key={i}><dt>{metric.label}</dt><dd>{ownershipValue(metric.value)}</dd></div>)}</dl>
    {!compact && kind === "insiders" && <div className={styles.history}>
      {points ? <><div><p className={styles.smallTitle}>Reported holdings · {points[0].label}</p><svg viewBox="0 0 240 64" role="img" aria-label={`Reported holdings observations from ${points[0].date} to ${points.at(-1)!.date}. ${card.history_note}`}><path d="M8 56H232" className={styles.chartBase}/><polyline points={plot} className={styles.chartLine}/>{points.map((point,i) => <circle key={i} cx={8 + i / (points.length - 1) * 224} cy={max === min ? 32 : 56 - (Number(point.value) - min) / (max - min) * 48} r="3"><title>{point.date}: {ownershipValue(point.value)} · {point.label}</title></circle>)}</svg><div className={styles.chartDates}><span>{points[0].date}</span><span>{points.at(-1)!.date}</span></div></div><details><summary>View exact observations</summary><ul className={styles.historyValues}>{points.map((point,i) => <li key={i}><span>{point.date}</span><strong>{ownershipValue(point.value)}</strong><span>{point.label}</span></li>)}</ul></details></> : <p className={styles.missing}>No compatible holding history to chart.</p>}
      <p className={styles.note}>{card.history_note || "A chart requires at least two observations for the same security and direct or indirect ownership bucket. It is not a total of this person's holdings."}</p>
    </div>}
    {kind === "institutions" && points && <div className={styles.history}><p className={styles.smallTitle}>Compatible reported positions · {points[0].label}</p><ul className={styles.historyValues}>{points.map((point,i) => <li key={i}><span>{point.date}</span><strong>{ownershipValue(point.value)}</strong><span>{point.label}</span></li>)}</ul></div>}
    {kind !== "insiders" && card.history_note && <p className={styles.note}>{card.history_note}</p>}
    <details className={styles.detail}><summary>View filings{card.transactions.length ? ` and ${card.transactions.length} reported record${card.transactions.length === 1 ? "" : "s"}` : " and context"}</summary>
      {card.transactions.length > 0 && <><OwnershipFacts rows={card.transactions} kind={kind}/>{card.transactions.some(row => Array.isArray(row.footnotes) && row.footnotes.length > 0) && <div className={styles.footnotes}><h4>Reported footnotes</h4>{card.transactions.map((row,i) => Array.isArray(row.footnotes) && row.footnotes.length ? <p key={i}>{ownershipValue(row.footnotes)}</p> : null)}</div>}</>}
      <ul className={styles.documents}>{card.documents.map(document => <li key={document.document_id}><div><Link href={ownershipSourceHref(cik, document, returnTo)}>{document.form} · Filed {document.filed_date}</Link><small>{document.filename}</small></div>{safeSourceUrl(document.source_url) && <a href={safeSourceUrl(document.source_url)!} target="_blank" rel="noreferrer">SEC source ↗</a>}</li>)}</ul>
      {!card.documents.length && <p className={styles.missing}>A readable source is not available for this record.</p>}
    </details>
  </article>;
}
