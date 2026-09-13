import Link from "next/link";
import { workspaceRequest } from "@/lib/workspace-api";
import { documentVersionParam } from "@/lib/research";
import { capturedDate, type DocumentVersions, type DocumentComparison } from "@/lib/document-history";
import styles from "./DocumentHistory.module.css";

export default async function DocumentHistory({ version, before, offset = 0 }: { version: string; before?: string; offset?: number }) {
  const path = `/research/documents/${encodeURIComponent(version)}`;
  const history = await workspaceRequest<DocumentVersions>(`${path}/history?limit=20&offset=${offset}`);
  if (!history.data) return <section className={styles.history}><h2>Captured versions</h2><p>Version history could not be loaded. The extracted text below remains available.</p></section>;
  const versions = history.data;
  const baseline = before ? documentVersionParam(before) : null;
  const comparison = baseline && baseline !== version ? await workspaceRequest<DocumentComparison>(`/research/compare?${new URLSearchParams({ before: baseline, after: version })}`) : null;
  const diff = comparison?.data;
  const href = (nextOffset: number) => `${path}?${new URLSearchParams({ ...(baseline ? { before: baseline } : {}), ...(nextOffset ? { history_offset: String(nextOffset) } : {}) })}#captured-versions`;
  return <section className={styles.history} id="captured-versions" aria-labelledby="history-title">
    <div className={styles.heading}><div><p className="eyebrow">Evidence history</p><h2 id="history-title">Captured versions</h2></div><span>{versions.total} {versions.total === 1 ? "version" : "versions"} recorded</span></div>
    <p>Compare text captured from this document. Capture times show when Disclosure indexed the content; separate filings and amendments have their own histories.</p>
    {versions.total === 1 ? <p className={styles.empty}>One captured version is available. Future captures with changed source bytes will appear here.</p> : <>
      <form action={`${path}#captured-versions`} className={styles.controls}>
        <label htmlFor="before-version">Compare this version with
          <select id="before-version" name="before" defaultValue={baseline || ""} required>
            <option value="" disabled>Select a captured version</option>
            {baseline && !versions.versions.some(item => item.version_id === baseline) && <option value={baseline}>Selected version · {baseline.slice(-12)}</option>}
            {versions.versions.map(item => <option key={item.version_id} value={item.version_id} disabled={item.version_id === version}>{capturedDate(item.indexed_at)} · {item.version_id.slice(-12)}{item.version_id === version ? " · viewing" : ""}</option>)}
          </select>
        </label>
        {offset > 0 && <input type="hidden" name="history_offset" value={offset}/>}
        <button type="submit" className="btn secondary">Compare captured text</button>
        {before && <Link href={`${path}#captured-versions`} className={styles.clear}>Clear comparison</Link>}
      </form>
      {(offset > 0 || versions.next_offset !== null) && <nav className={styles.paging} aria-label="Captured version pages"><span>Showing {offset + 1}–{offset + versions.versions.length} of {versions.total}</span>{offset > 0 && <Link href={href(Math.max(0, offset - 20))}>Newer captures</Link>}{versions.next_offset !== null && <Link href={href(versions.next_offset)}>Older captures</Link>}</nav>}
    </>}
    {before && !baseline && <p role="alert">The selected version ID is invalid. Choose a captured version above.</p>}
    {baseline === version && <p role="status">This is the version you are already viewing. Choose a different capture to compare.</p>}
    {comparison && !diff && <p role="alert">{comparison.status === 404 ? "One of these captured versions is unavailable." : comparison.status === 422 ? "Only two captured versions of the same document can be compared." : "The comparison could not be loaded. Try again."}</p>}
    {diff && <div className={styles.comparison} aria-label="Captured text comparison">
      <div className={styles.versions}>
        <div><span className={styles.removed}>− Before</span><Link href={`/research/documents/${encodeURIComponent(diff.before.version_id)}`}>{capturedDate(diff.before.indexed_at)}</Link><small>{diff.before.version_id.slice(-12)}</small></div>
        <div><span className={styles.added}>+ After · viewing</span><Link href={`/research/documents/${encodeURIComponent(diff.after.version_id)}`}>{capturedDate(diff.after.indexed_at)}</Link><small>{diff.after.version_id.slice(-12)}</small></div>
      </div>
      {!diff.complete && <div className="notice" role="status"><strong>Partial comparison.</strong> {diff.input_truncated ? "The source text exceeds the comparison limit. " : ""}{diff.output_truncated ? "Some changes exceed the display limit. " : ""}Open both captured versions to review the complete extracted text.</div>}
      {diff.text_identical && <p className={styles.empty}>{diff.complete ? "The extracted text is identical. Source bytes or formatting may still differ." : "No text changes were found in the compared portion. This does not establish that the complete documents match."}</p>}
      {diff.hunks.map((hunk, index) => <section key={index} className={styles.hunk} aria-label={`Change ${index + 1}`}>
        <div className={styles.range}>Before line {hunk.before_start} · After line {hunk.after_start}</div>
        {hunk.lines.map((line, number) => <div key={number} className={`${styles.line} ${line.kind === "delete" ? styles.deletion : line.kind === "insert" ? styles.insertion : ""}`}>
          <span className={styles.lineNumber} aria-label={`Before line ${line.before_line ?? "none"}`}>{line.before_line ?? ""}</span><span className={styles.lineNumber} aria-label={`After line ${line.after_line ?? "none"}`}>{line.after_line ?? ""}</span>
          <span className={styles.marker} aria-label={line.kind === "delete" ? "Removed" : line.kind === "insert" ? "Added" : "Unchanged"}>{line.kind === "delete" ? "−" : line.kind === "insert" ? "+" : " "}</span><pre>{line.text}</pre>
        </div>)}
      </section>)}
      <details className={styles.method}><summary>Comparison scope</summary><p>{diff.coverage.before_characters_compared.toLocaleString("en-GB")} of {diff.coverage.before_characters_total.toLocaleString("en-GB")} characters before; {diff.coverage.after_characters_compared.toLocaleString("en-GB")} of {diff.coverage.after_characters_total.toLocaleString("en-GB")} after.</p><ul>{diff.limitations.map(item => <li key={item}>{item}</li>)}</ul></details>
    </div>}
  </section>;
}
