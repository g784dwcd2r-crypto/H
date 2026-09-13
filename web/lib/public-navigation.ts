export type PublicLink = { label: string; href: string; description: string };
export type PublicMenu = {
  id: string;
  label: string;
  href: string;
  links?: PublicLink[];
  feature?: { label: string; title: string; description: string; href: string };
};

export const PUBLIC_MENUS: PublicMenu[] = [
  {
    id: "platform", label: "Platform", href: "/platform",
    links: [
      { label: "Overview", href: "/platform", description: "A connected workspace for company research." },
      { label: "Filings & search", href: "/platform#filings", description: "Find disclosures and read them in context." },
      { label: "Financials & Excel", href: "/platform#financials", description: "Compare reported figures and export your periods." },
      { label: "Ownership", href: "/platform#ownership", description: "Distinguish insiders from institutional investors." },
      { label: "Cited research", href: "/platform#research", description: "Explore questions with evidence you can inspect." },
      { label: "Watchlists & alerts", href: "/platform#watchlists", description: "Follow companies and return to what changed." },
      { label: "Projects", href: "/platform#projects", description: "Keep your analysis and supporting sources together." },
      { label: "Company comparison", href: "/platform#comparison", description: "Put companies and reported periods side by side." },
    ],
    feature: { label: "Inside Disclosure", title: "From a number to its source.", description: "Inspect the filing behind a financial figure, then carry its context into your analysis.", href: "/platform#financials" },
  },
  {
    id: "solutions", label: "Solutions", href: "/solutions",
    links: [
      { label: "Earnings preparation", href: "/solutions#earnings", description: "Bring prior results, filings and questions together." },
      { label: "Company due diligence", href: "/solutions#due-diligence", description: "Build an understanding from original disclosures." },
      { label: "Financial comparison", href: "/solutions#comparison", description: "Examine differences across companies and periods." },
      { label: "Ownership monitoring", href: "/solutions#ownership", description: "Understand who is reporting, their role and changes." },
      { label: "Portfolio monitoring", href: "/solutions#portfolio", description: "Keep followed companies in a focused research flow." },
      { label: "Team research", href: "/solutions#team-research", description: "Discuss how Disclosure fits your team's workflow." },
    ],
    feature: { label: "A research workflow", title: "Prepare for the next earnings release.", description: "Review the last period, inspect what changed and organise the questions that matter.", href: "/solutions#earnings" },
  },
  { id: "coverage", label: "Coverage", href: "/coverage" },
  { id: "security", label: "Security", href: "/security" },
  {
    id: "resources", label: "Resources", href: "/resources",
    links: [
      { label: "Getting started", href: "/resources#getting-started", description: "Find your first company and start exploring." },
      { label: "Research guides", href: "/resources#guides", description: "Practical steps from filings to a working analysis." },
      { label: "Data methodology", href: "/resources#methodology", description: "Understand sources, periods and reported figures." },
      { label: "Product updates", href: "/resources#updates", description: "See what is available and what has changed." },
      { label: "Frequently asked questions", href: "/resources#faq", description: "Coverage, access, exports and the founding offer." },
    ],
    feature: { label: "Start here", title: "Your first company research session.", description: "A guided route through a company, its financials and the documents behind them.", href: "/resources#getting-started" },
  },
  {
    id: "company", label: "Company", href: "/company/about",
    links: [
      { label: "About Disclosure", href: "/company/about", description: "Why we are building a clearer way to research." },
      { label: "Contact", href: "/company/contact", description: "Talk to us about your research and your team." },
    ],
    feature: { label: "Our purpose", title: "Company research. Clearly organised.", description: "Bring filings, financials and their evidence into a workspace that helps you think.", href: "/company/about" },
  },
];

export const LOGIN_REGIONS = [
  { code: "US", label: "United States", symbol: "🇺🇸" },
  { code: "UK", label: "United Kingdom", symbol: "🇬🇧" },
  { code: "EU", label: "Europe", symbol: "🇪🇺" },
  { code: "AU", label: "Australia", symbol: "🇦🇺" },
  { code: "ROW", label: "Rest of the world", symbol: "🌐" },
] as const;

export type LoginRegion = (typeof LOGIN_REGIONS)[number]["code"];
export function validLoginRegion(value: unknown): value is LoginRegion {
  return LOGIN_REGIONS.some(region => region.code === value);
}

export function isPublicPath(path: string) {
  return path === "/" || ["/platform", "/solutions", "/coverage", "/security", "/resources", "/company", "/demo", "/early-access", "/privacy"].some(prefix => path === prefix || path.startsWith(prefix + "/"));
}
