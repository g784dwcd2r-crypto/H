import Link from "next/link";
import styles from "./Marketing.module.css";

export type MarketingSection = { id:string; title:string; description:string; steps:string[]; example?:string; note?:string; href:string; action:string };
export default function MarketingPage({ eyebrow,title,intro,sections }: { eyebrow:string;title:string;intro:string;sections:MarketingSection[] }) {
  return <div className={styles.page}><div className={styles.hero}><p className="eyebrow">{eyebrow}</p><h1>{title}</h1><p>{intro}</p><div className={styles.actions}><Link href="/demo" className="btn">Request a demo →</Link><Link href="/companies/320193" className="text-link">Explore a company</Link></div></div><nav className={styles.jump} aria-label={`${eyebrow} topics`}>{sections.map(s=><a key={s.id} href={`#${s.id}`}>{s.title}</a>)}</nav>
    {sections.map((s,index)=><section className={styles.section} id={s.id} key={s.id}><div><p className={styles.number}>{String(index+1).padStart(2,"0")} / {eyebrow}</p><h2>{s.title}</h2><p>{s.description}</p></div><div><ol className={styles.steps}>{s.steps.map(step=><li key={step}>{step}</li>)}</ol>{s.example&&<div className={styles.example}><strong>Put it to work</strong><p>{s.example}</p></div>}{s.note&&<p className={styles.note}>{s.note}</p>}<Link href={s.href} className="text-link">{s.action} →</Link></div></section>)}
    <section className={styles.feature}><div><p className="eyebrow">Make it your workflow</p><h2>Bring a company. Start with a question.</h2></div><div><p>We’ll walk through the filings, figures and research tools that matter to your work, with a clear view of the available coverage.</p><Link href="/demo" className="btn">Request a demo</Link></div></section>
  </div>;
}
