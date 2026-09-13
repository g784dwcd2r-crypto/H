"use client";
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import CitedSourcePicker, { type SelectedCompany, type SelectedDocument } from "./CitedSourcePicker";
import CitedEvidence from "./CitedEvidence";
import { citedRequest, runRequestKey, runStatusLabel, type CitedRun, type ResearchCapabilities, type ResearchPassage, type RunRequest } from "@/lib/cited-research";
import { projectRequest } from "@/lib/project-client";
import type { Project } from "@/lib/workspace-types";
import type { IndexedDocument } from "@/lib/research";
import type { EvidenceNumber } from "@/lib/evidence-span";
import { readResearchDraft, writeResearchDraft, clearResearchDraft } from "@/lib/research-drafts";
import "./cited-research.css";

type Picked = EvidenceNumber & { passage: ResearchPassage };
export default function CitedResearchWorkspace({ signedIn, accountId, capabilities, initialRun, initialDocument, initialError }: { signedIn: boolean; accountId: string | null; capabilities: ResearchCapabilities | null; initialRun: CitedRun | null; initialDocument: IndexedDocument | null; initialError: string | null }) {
  const [run, setRun] = useState(initialRun);
  const [question, setQuestion] = useState(initialRun?.question || "");
  const [companies, setCompanies] = useState<SelectedCompany[]>(initialRun?.ciks.map(cik => ({ cik, name: `CIK ${cik}` })) || []);
  const [documents, setDocuments] = useState<SelectedDocument[]>(initialDocument ? [initialDocument] : initialRun?.version_ids.map(version_id => ({ version_id, title: initialRun.passages.find(p => p.version_id === version_id)?.title || "Selected source version", cik: initialRun.passages.find(p => p.version_id === version_id)?.cik || 0, filed_date: initialRun.passages.find(p => p.version_id === version_id)?.filed_date || "" })) || []);
  const [cutoff, setCutoff] = useState(initialRun?.as_of || new Date().toISOString().slice(0, 10));
  const [parent, setParent] = useState<string | undefined>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(initialError);
  const [notice, setNotice] = useState<string | null>(null);
  const [selected, setSelected] = useState<ResearchPassage | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectId, setProjectId] = useState("");
  const [numbers, setNumbers] = useState<Picked[]>([]);
  const [unit, setUnit] = useState("");
  const [operation, setOperation] = useState("growth");
  const retry = useRef<{ fingerprint: string; key: string } | null>(null);
  const calcRetry = useRef<{ fingerprint: string; key: string } | null>(null);
  const [draftReady, setDraftReady] = useState(false);
  const [durableDraft, setDurableDraft] = useState(true);
  const draftContext = run?.id || initialDocument?.version_id || "new";
  const draftStorage = () => { try { return window.sessionStorage; } catch { return null; } };
  const draftValue = () => ({question, companies, documents, cutoff, parent, request: retry.current});
  useEffect(() => {
    if (accountId && !initialError) {
      const recovered = readResearchDraft(draftStorage(), accountId, initialRun?.id || initialDocument?.version_id || "new");
      if (recovered) {
        setQuestion(recovered.question); setCompanies(recovered.companies); setDocuments(recovered.documents); setCutoff(recovered.cutoff); setParent(recovered.parent); retry.current = recovered.request;
        setNotice("Your question draft and source scope were recovered in this tab. Source and project access will be checked again before use.");
      }
    }
    setDraftReady(true);
    // The server rechecks the account and requested run/source before allowing recovery.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [accountId, initialRun?.id, initialDocument?.version_id, initialError]);
  const hasDraft = !!parent || !!question.trim() && (!run || question !== run.question || cutoff !== run.as_of || JSON.stringify(companies.map(c=>c.cik).sort()) !== JSON.stringify([...run.ciks].sort()) || JSON.stringify(documents.map(d=>d.version_id).sort()) !== JSON.stringify([...run.version_ids].sort()));
  useEffect(() => {
    if (!draftReady || !accountId || initialError) return;
    if (hasDraft) setDurableDraft(writeResearchDraft(draftStorage(), accountId, draftContext, draftValue()));
    else clearResearchDraft(draftStorage(), accountId, draftContext);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draftReady,accountId,initialError,draftContext,question,companies,documents,cutoff,parent,hasDraft]);
  useEffect(() => {
    if (!hasDraft) return;
    const guard = (event:BeforeUnloadEvent) => { if (!durableDraft || busy) { event.preventDefault(); event.returnValue=""; } };
    window.addEventListener("beforeunload",guard); return () => window.removeEventListener("beforeunload",guard);
  }, [hasDraft,durableDraft,busy]);
  useEffect(() => { if (!signedIn) return; let active = true; projectRequest<{ projects: Project[] }>("").then(data => { if (active) setProjects(data.projects); }).catch(() => { if (active) setNotice("Projects could not be loaded. Research can still be reviewed before saving."); }); return () => { active = false; }; }, [signedIn]);
  useEffect(() => {
    if (run?.status !== "running") return;
    let active = true;
    const timer = setInterval(() => { citedRequest<CitedRun>(`/runs/${run.id}`).then(value => { if (active) setRun(value); }).catch(cause => { if (active) setError(cause.message); }); }, 3000);
    return () => { active = false; clearInterval(timer); };
  }, [run?.id, run?.status]);
  const acceptRun = (value: CitedRun) => { setRun(value); window.history.replaceState(null, "", `/research/ask?run=${value.id}`); };
  const ask = async () => {
    const body: Omit<RunRequest, "idempotency_key"> = { question, ciks: companies.map(c => c.cik), version_ids: documents.map(d => d.version_id), as_of: cutoff, ...(parent ? { parent_run_id: parent } : {}) };
    const fingerprint = runRequestKey(body);
    if (retry.current?.fingerprint !== fingerprint) retry.current = { fingerprint, key: crypto.randomUUID() };
    if (accountId) setDurableDraft(writeResearchDraft(draftStorage(), accountId, draftContext, draftValue()));
    setBusy(true); setError(null); setNotice(null); setSelected(null);
    try { const value = await citedRequest<CitedRun>("/runs", "POST", { ...body, idempotency_key: retry.current.key }); if (accountId) clearResearchDraft(draftStorage(), accountId, draftContext); acceptRun(value); setParent(undefined); setNumbers([]); if (value.status === "failed") setError(value.limitations.at(-1) || "Research could not finish."); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "The question could not be completed."); }
    finally { setBusy(false); }
  };
  const calculating = !!run && !run.project_id && !["running", "failed"].includes(run.status);
  return <>
    {(!capabilities || !capabilities.available) && <section className="notice" role="status"><strong>Source questions are not available on this deployment yet.</strong>{capabilities?.unavailable_reason === "corpus_not_prepared" && <p>The indexed source corpus is not prepared for this retrieval model yet.</p>}{capabilities?.provider.readiness === "account_unfunded" && <p>The configured provider account needs credits or a license before live research can run.</p>}<p>{capabilities ? "The provider must have verified model access, billing readiness and a prepared source corpus for its configured retrieval mode. You can still search and inspect indexed filings." : "The research service could not be reached. Your source search remains separate."}</p><Link href="/research">Search indexed filings →</Link></section>}
    {(capabilities?.provider.fixture || run?.provider.fixture) && <p className="notice err"><strong>Synthetic demonstration.</strong> These answers use a deterministic test provider. They are not live model acceptance or investment research.</p>}
    {!signedIn && <p className="notice">Research runs are private. <Link href="/signin">Sign in</Link> to ask a question and save its evidence.</p>}
    {hasDraft && !durableDraft && <p className="notice err" role="status">Browser draft storage is unavailable. Keep this tab open to retain your question.</p>}
    {error && <p className="notice err" role="alert">{error}</p>}{notice && <p className="notice" role="status">{notice}</p>}
    <div className="cited-workbench">
      <form className="cited-question-form" onSubmit={event => { event.preventDefault(); void ask(); }}>
        <fieldset disabled={busy || run?.status === "running"}><CitedSourcePicker companies={companies} documents={documents} onCompanies={setCompanies} onDocuments={setDocuments} locked={!!parent} maxCompanies={capabilities?.bounds.max_companies || 12} maxDocuments={capabilities?.bounds.max_documents || 50}/>
          <label className="cited-cutoff">Historical cutoff<input type="date" value={cutoff} max={new Date().toISOString().slice(0, 10)} onChange={event => setCutoff(event.target.value)} required disabled={!!parent}/></label><p className="security-footnote">Both the filing date and source-capture date must be on or before this UTC day. A filing captured later is excluded even if it was originally published earlier.</p>
          <label className="cited-question-label" htmlFor="research-question">2. {parent ? "Ask a follow-up" : "Ask your question"}</label><textarea id="research-question" value={question} onChange={event => setQuestion(event.target.value)} placeholder="What does management say about liquidity, and what qualifications or contrary evidence should I consider?" rows={4} minLength={3} maxLength={2000} required/>
          <div className="cited-submit-row"><button className="btn" type="submit" disabled={!signedIn || !capabilities?.available || !cutoff || question.trim().length < 3 || !companies.length && !documents.length}>{busy ? "Reviewing selected evidence…" : parent ? "Research follow-up" : "Ask with sources"}</button>{parent && <button className="linkbtn" type="button" onClick={() => { setParent(undefined); setNotice("New question: you can change the sources and cutoff."); }}>Start a new question</button>}</div>
          <p className="security-footnote">Up to 12 retrieved passages, three bounded provider calls and 20 runs per day. Questions stay in this tab if a request fails; retrying the same request reuses its run.</p>
        </fieldset>
      </form>
      <section className="cited-answer" aria-label="Research answer" aria-live="polite">
        {!run ? <div className="cited-empty"><p className="eyebrow">A research draft you can inspect</p><h2>The conclusion comes with its evidence.</h2><p>Select the source material and a cutoff, then ask a focused question. Review supporting and contradictory passages before developing your own view.</p><ol><li>Every released claim points to exact source text.</li><li>Insufficient evidence remains explicit.</li><li>Calculations use the original numbers you select.</li></ol></div> : <>
          <div className="cited-run-heading"><p className="eyebrow">{runStatusLabel(run.status)}</p><h2>{run.question}</h2><p>Cutoff {run.as_of} · {run.coverage.eligible_documents} eligible documents · {run.coverage.retrieved_passages} passages retrieved</p></div>
          {run.status === "running" && <p role="status">Research is running. This page checks for the same saved run; it does not start duplicate provider requests.</p>}
          {run.status === "insufficient_evidence" && <p className="notice">The selected evidence does not establish a complete answer. Review any supported fragments and the retrieval limits below.</p>}
          {run.status === "conflicting_evidence" && <p className="notice">The source passages include counter-evidence. Inspect the qualifications before relying on a conclusion.</p>}
          {run.claims.map(claim => <article className="cited-claim" key={claim.id}><p>{claim.text}</p><small>Machine-assessed support · analyst review required</small><ul>{claim.evidence.map((evidence, i) => { const passage = run.passages.find(p => p.span_id === evidence.span_id); return <li key={`${evidence.span_id}-${i}`} className={`evidence-${evidence.relationship}`}><span>{evidence.relationship === "contradictory" ? "Counter-evidence" : evidence.relationship === "supporting" ? "Supporting passage" : "Context"}</span><blockquote>{evidence.quote}</blockquote>{passage && <button className="linkbtn" onClick={() => setSelected(passage)}>Inspect {passage.title} · {passage.filed_date} →</button>}</li>; })}</ul></article>)}
          {run.passages.length > 0 && <details className="cited-all-passages"><summary>Review all retrieved passages ({run.passages.length})</summary><p>A passage can be relevant without supporting a released claim. Retrieval does not prove all relevant evidence was found.</p>{run.passages.map(passage => <button type="button" key={passage.span_id} onClick={() => setSelected(passage)}><strong>{passage.title}</strong><span>{passage.form} · {passage.filed_date}</span><p>{passage.text.slice(0, 200)}…</p></button>)}</details>}
          {run.calculations.length > 0 && <section className="cited-calculations"><h3>Source calculations</h3>{run.calculations.map(calculation => <article key={calculation.id}><strong>{calculation.value} {calculation.unit}</strong><p>{calculation.formula} · A = {calculation.operands[0].text}, B = {calculation.operands[1].text}</p><p className="security-footnote">{calculation.limitations.join(" ")}</p>{calculation.operands.map((operand, i) => <button key={i} className="linkbtn" onClick={() => setSelected(run.passages.find(p => p.span_id === operand.span_id) || null)}>Inspect operand {i ? "B" : "A"} →</button>)}</article>)}</section>}
          {calculating && numbers.length > 0 && <section className="cited-calculator"><h3>Calculate from selected source numbers</h3><p>A = {numbers[0]?.text || "Select a source number"} · B = {numbers[1]?.text || "Select another source number"}</p><label>Operation<select aria-label="Operation" value={operation} onChange={e => setOperation(e.target.value)}><option value="growth">Growth: (A − B) / B × 100</option><option value="difference">Difference: A − B</option><option value="ratio">Ratio: A / B</option><option value="sum">Sum: A + B</option></select></label><label>Same unit for both operands<input value={unit} onChange={e => setUnit(e.target.value)} placeholder="For example, USD millions" maxLength={50}/></label><p className="security-footnote">Check each number’s period, unit and meaning in its source. Disclosure does not infer accounting comparability or convert currencies.</p><button className="btn secondary" disabled={busy || numbers.length !== 2 || !unit.trim()} onClick={async () => { const body = { operation, operands: numbers.map(n => ({ span_id: n.passage.span_id, start: n.start, end: n.end, unit: unit.trim() })) }; const fingerprint = JSON.stringify(body); if (calcRetry.current?.fingerprint !== fingerprint) calcRetry.current = { fingerprint, key: crypto.randomUUID() }; setBusy(true); setError(null); try { acceptRun(await citedRequest<CitedRun>(`/runs/${run.id}/calculations`, "POST", { ...body, idempotency_key: calcRetry.current.key })); setNumbers([]); } catch (e) { setError(e instanceof Error ? e.message : "Calculation failed."); } finally { setBusy(false); } }}>Calculate exactly</button><button className="linkbtn" onClick={() => setNumbers([])}>Clear numbers</button></section>}
          <details className="cited-limits"><summary>Coverage, limits and provider use</summary><p>{run.provider.provider} · {run.provider.model || "No model"} · {run.usage.provider_calls} calls · {run.usage.input_tokens} input / {run.usage.output_tokens} output tokens reported</p><p>{run.coverage.excluded_after_cutoff} captures excluded after the cutoff. {run.coverage.partial ? "The registered scope is incomplete." : "Completeness applies only to this registered selection."}</p><ul>{run.limitations.map((item, i) => <li key={i}>{item}</li>)}</ul></details>
          {!["running", "failed"].includes(run.status) && <div className="cited-save"><button className="btn secondary" disabled={busy} onClick={() => { setParent(run.id); setQuestion(""); setCompanies(run.ciks.map(cik => ({ cik, name: `CIK ${cik}` }))); setDocuments(run.version_ids.map(version_id => ({ version_id, title: run.passages.find(p => p.version_id === version_id)?.title || "Selected source version", cik: run.passages.find(p => p.version_id === version_id)?.cik || 0, filed_date: run.passages.find(p => p.version_id === version_id)?.filed_date || "" }))); setCutoff(run.as_of); document.getElementById("research-question")?.focus(); }}>Ask a follow-up</button>{run.project_id ? <p>Saved research artifact. <Link href={`/projects/${run.project_id}`}>Open project →</Link></p> : <><label>Save this result and evidence<select aria-label="Save this result and evidence" value={projectId} onChange={e => setProjectId(e.target.value)}><option value="">Select an authorized project</option>{projects.map(project => <option key={project.id} value={project.id}>{project.name}</option>)}</select></label><button className="btn" disabled={busy || !projectId} onClick={async () => { setBusy(true); setError(null); try { acceptRun(await citedRequest<CitedRun>(`/runs/${run.id}/save`, "POST", { project_id: projectId })); setNotice("Result, exact evidence and calculations saved to the project."); } catch (e) { setError(e instanceof Error ? e.message : "The result could not be saved."); } finally { setBusy(false); } }}>Save research</button>{!projects.length && <Link href="/projects">Create a project first →</Link>}</>}</div>}
        </>}
      </section>
    </div>
    {selected && <CitedEvidence passage={selected} onClose={() => setSelected(null)} canCalculate={calculating && !busy} onNumber={(number, passage) => { setNumbers(previous => previous.length >= 2 ? [{ ...number, passage }] : [...previous, { ...number, passage }]); setNotice("Source number selected. Review the calculation panel and set its unit."); }}/ >}
  </>;
}
