// Workspace transitions retain a loading skeleton. Public pages wait for readable server content.
export default function WorkspaceLoading() {
  return <div className="loading-state" role="status"><p className="eyebrow">Disclosure</p><h1>Opening your workspace…</h1><div className="loading-line" /><div className="loading-line short" /><span className="sr-only">Loading page content.</span></div>;
}
