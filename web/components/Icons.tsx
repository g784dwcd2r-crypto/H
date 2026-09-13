import type { SVGProps } from "react";
type Props = SVGProps<SVGSVGElement>;
const common = { fill: "none", stroke: "currentColor", strokeWidth: 1.5, strokeLinecap: "round" as const, strokeLinejoin: "round" as const, viewBox: "0 0 24 24", "aria-hidden": true as const };
export function SearchIcon(props: Props) { return <svg {...common} {...props}><circle cx="10.5" cy="10.5" r="6.5" /><path d="m16 16 5 5" /></svg>; }
export function ArrowIcon(props: Props) { return <svg {...common} {...props}><path d="M4 12h16m-6-6 6 6-6 6" /></svg>; }
export function DocumentIcon(props: Props) { return <svg {...common} {...props}><path d="M6 3h8l4 4v14H6V3Z" /><path d="M14 3v5h4M9 12h6M9 16h6" /></svg>; }
export function StarIcon(props: Props) { return <svg {...common} {...props}><path d="m12 3 2.8 5.7 6.2.9-4.5 4.4 1.1 6.2-5.6-3-5.6 3 1.1-6.2L3 9.6l6.2-.9L12 3Z" /></svg>; }
export function SettingsIcon(props: Props) { return <svg {...common} {...props}><path d="m10 3-.5 2-2 .9-1.9-.6-2 3.4 1.5 1.5v2.6l-1.5 1.5 2 3.4 1.9-.6 2 .9.5 2h4l.5-2 2-.9 1.9.6 2-3.4-1.5-1.5v-2.6l1.5-1.5-2-3.4-1.9.6-2-.9L14 3h-4Z" /><circle cx="12" cy="11.5" r="3" /></svg>; }
export function ExportIcon(props: Props) { return <svg {...common} {...props}><path d="M5 10v10h14V10M12 15V3m-4 4 4-4 4 4" /></svg>; }
