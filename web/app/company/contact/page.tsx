import Link from "next/link";
import DemoRequestForm from "@/components/DemoRequestForm";
import styles from "@/components/Marketing.module.css";
export const metadata={title:"Contact Disclosure"};
export default function Page(){return <div className={`${styles.page} ${styles.formGrid}`}><div className={styles.hero}><p className="eyebrow">Contact</p><h1>Tell us what matters to your work.</h1><p>Questions about the product, your account, coverage or the founding group? Send us a message.</p><p className={styles.note}>For a walkthrough, <Link href="/demo">request a demo</Link>. For a new market or company, you can also <Link href="/coverage">check coverage and register interest</Link>.</p></div><div className={styles.formCard}><DemoRequestForm contact/></div></div>;}
