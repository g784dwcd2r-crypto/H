import type { SelectedCompany, SelectedDocument } from "@/components/CitedSourcePicker";
export type ResearchDraft = { question: string; companies: SelectedCompany[]; documents: SelectedDocument[]; cutoff: string; parent?: string; request: {fingerprint:string;key:string} | null };
type Saved = { version:1; accountId:string; context:string; draft:ResearchDraft };
const memory = new Map<string,Saved>();
const key = (accountId:string,context:string) => `disclosure:research-draft:v1:${encodeURIComponent(accountId)}:${encodeURIComponent(context)}`;
export function readResearchDraft(storage:Pick<Storage,"getItem">|null,accountId:string,context:string):ResearchDraft|null {
  let item:Saved|undefined;
  try { const value=storage?.getItem(key(accountId,context)); item=value?JSON.parse(value):memory.get(key(accountId,context)); } catch { item=memory.get(key(accountId,context)); }
  if(!item || item.version!==1 || item.accountId!==accountId || item.context!==context) return null;
  const d=item.draft;
  if(!d || typeof d.question!=="string" || d.question.length>2000 || typeof d.cutoff!=="string" || !/^\d{4}-\d{2}-\d{2}$/.test(d.cutoff) || d.parent!==undefined && !/^[a-f0-9]{32}$/.test(d.parent))return null;
  if(!Array.isArray(d.companies) || d.companies.length>12 || !d.companies.every(c=>c&&Number.isInteger(c.cik)&&c.cik>0&&c.cik<1e10&&typeof c.name==="string"&&c.name.length<=300))return null;
  if(!Array.isArray(d.documents)||d.documents.length>50||!d.documents.every(v=>v&&/^sha256:[a-f0-9]{64}$/.test(v.version_id)&&typeof v.title==="string"&&v.title.length<=1000&&Number.isInteger(v.cik)&&typeof v.filed_date==="string"))return null;
  if(d.request!==null&&(!d.request||typeof d.request.fingerprint!=="string"||d.request.fingerprint.length>20000||!/^[-a-zA-Z0-9_]{8,100}$/.test(d.request.key)))return null;
  // Local source labels are display hints only. The API rechecks scope and access before use.
  return d;
}
export function writeResearchDraft(storage:Pick<Storage,"setItem">|null,accountId:string,context:string,draft:ResearchDraft):boolean {
  const saved:Saved={version:1,accountId,context,draft};memory.set(key(accountId,context),saved);
  try{if(!storage)return false;storage.setItem(key(accountId,context),JSON.stringify(saved));return true;}catch{return false;}
}
export function clearResearchDraft(storage:Pick<Storage,"removeItem">|null,accountId:string,context:string):void {
  memory.delete(key(accountId,context));try{storage?.removeItem(key(accountId,context));}catch{/* A later write supersedes it. */}
}
