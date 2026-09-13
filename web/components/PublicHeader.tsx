"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
import Brand from "./Brand";
import { PublicNavigationContext } from "./PublicNavigationContext";
import { PUBLIC_MENUS, type PublicMenu } from "@/lib/public-navigation";
import styles from "./PublicHeader.module.css";

export function MenuChevron() {
  return <svg className={styles.chevron} viewBox="0 0 16 16" aria-hidden="true" fill="none"><path d="m4 6 4 4 4-4" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" /></svg>;
}

function Feature({ menu, close }: { menu: PublicMenu; close: () => void }) {
  if (!menu.feature) return null;
  return (
    <Link href={menu.feature.href} className={styles.feature} onClick={close}>
      <div className={`${styles.featureArt} ${styles["art_" + menu.id]}`} aria-hidden="true">
        {menu.id === "platform" ? <div className={styles.numberPreview}>
          <span>APPLE INC. · HISTORICAL EXAMPLE</span>
          <div><span>Total net sales</span><strong>391,035</strong></div>
          <p>FY 2024 · USD millions</p>
          <div className={styles.sourcePreview}><svg viewBox="0 0 24 24" fill="none"><path d="M14 3H5v18h14V8l-5-5Z M14 3v5h5 M8 12h8 M8 16h6" stroke="currentColor" strokeWidth="1.2" /></svg><span>View the original disclosure <span>↗</span></span></div>
        </div> : menu.id === "solutions" ? <div className={styles.workflowPreview}>
          {["Review the prior period", "Read the evidence", "Prepare your questions"].map((step, index) => <div key={step}><span>0{index + 1}</span>{step}</div>)}
        </div> : menu.id === "resources" ? <div className={styles.guidePreview}><span>THE DISCLOSURE GUIDE</span><p>Find. Understand.<br />Make it your own.</p><span>YOUR FIRST RESEARCH SESSION <b>↗</b></span></div> : <div className={styles.companyPreview}><span>Disclosure</span><p>The source.<br />The context.<br />Your perspective.</p></div>}
      </div>
      <span className={styles.featureLabel}>{menu.feature.label}</span>
      <span className={styles.featureTitle}>{menu.feature.title} <span aria-hidden="true">↗</span></span>
      <span className={styles.featureDescription}>{menu.feature.description}</span>
    </Link>
  );
}

export default function PublicHeader({ userMenu }: { userMenu: ReactNode }) {
  const pathname = usePathname();
  const [active, setActive] = useState<string | null>(null);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [panelHeight, setPanelHeight] = useState<number | null>(null);
  const header = useRef<HTMLElement>(null);
  const lastTrigger = useRef<HTMLButtonElement | null>(null);
  const mobileTrigger = useRef<HTMLButtonElement>(null);
  const close = (restoreFocus = false) => {
    setActive(null);
    if (restoreFocus) lastTrigger.current?.focus();
  };
  const closeAll = () => { setActive(null); setMobileOpen(false); };
  const toggle = (id: string, trigger: HTMLButtonElement) => {
    lastTrigger.current = trigger;
    setActive(current => current === id ? null : id);
  };
  useEffect(() => { setActive(null); setMobileOpen(false); }, [pathname]);
  useEffect(() => {
    if (!active && !mobileOpen) return;
    const fit = () => {
      const bottom = header.current?.getBoundingClientRect().bottom ?? 86;
      setPanelHeight(Math.max(120, window.innerHeight - bottom));
    };
    fit();
    window.addEventListener("resize", fit);
    window.addEventListener("scroll", fit, { passive: true });
    return () => { window.removeEventListener("resize", fit); window.removeEventListener("scroll", fit); };
  }, [active, mobileOpen]);
  useEffect(() => {
    const outside = (event: PointerEvent | FocusEvent) => {
      if (event.target instanceof Node && !header.current?.contains(event.target)) { setActive(null); setMobileOpen(false); }
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || (!active && !mobileOpen)) return;
      event.preventDefault();
      if (active) { setActive(null); lastTrigger.current?.focus(); }
      else { setMobileOpen(false); mobileTrigger.current?.focus(); }
    };
    document.addEventListener("pointerdown", outside);
    document.addEventListener("focusin", outside);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("pointerdown", outside);
      document.removeEventListener("focusin", outside);
      document.removeEventListener("keydown", escape);
    };
  }, [active, mobileOpen]);
  useEffect(() => {
    const desktop = window.matchMedia("(min-width: 1120px)");
    const change = () => { setActive(null); setMobileOpen(false); };
    desktop.addEventListener("change", change);
    return () => desktop.removeEventListener("change", change);
  }, []);

  return (
    <PublicNavigationContext.Provider value={{ active, toggle, close: (restore = false) => { close(restore); if (!restore) setMobileOpen(false); } }}>
      <header ref={header} className={styles.header} data-public-header="true" style={panelHeight === null ? undefined : { "--public-panel-height": `${panelHeight}px` } as CSSProperties}>
        <div className={styles.row}>
          <Brand />
          <div id="public-navigation" className={`${styles.navigation} ${mobileOpen ? styles.mobileOpen : ""}`}>
            <nav className={styles.links} aria-label="Main navigation">
              {PUBLIC_MENUS.map(menu => {
                const selected = pathname === menu.href || pathname.startsWith("/" + menu.id + "/");
                return <div className={styles.navItem} key={menu.id}>
                  {menu.links ? <>
                    <button id={`nav-${menu.id}`} type="button" className={`${styles.navTrigger} ${selected ? styles.current : ""}`} aria-expanded={active === menu.id} aria-controls={`panel-${menu.id}`} onClick={event => toggle(menu.id, event.currentTarget)}>{menu.label}<MenuChevron /></button>
                    {active === menu.id && <div id={`panel-${menu.id}`} aria-labelledby={`nav-${menu.id}`} className={`${styles.panel} ${menu.id === "company" ? styles.compactPanel : ""}`}>
                      <div className={styles.panelInner}>
                        <div className={styles.linkGrid}>{menu.links.map(link => <Link key={link.href} href={link.href} className={styles.destination} onClick={closeAll}><span>{link.label} <span aria-hidden="true">↗</span></span><p>{link.description}</p></Link>)}</div>
                        <Feature menu={menu} close={closeAll} />
                      </div>
                    </div>}
                  </> : <Link className={`${styles.navTrigger} ${selected ? styles.current : ""}`} href={menu.href} aria-current={selected ? "page" : undefined} onClick={closeAll}>{menu.label}</Link>}
                </div>;
              })}
            </nav>
            <div className={styles.account}>{userMenu}</div>
          </div>
          <button ref={mobileTrigger} className={styles.mobileToggle} type="button" aria-expanded={mobileOpen} aria-controls="public-navigation" onClick={() => { setActive(null); setMobileOpen(current => !current); }}>
            <span>{mobileOpen ? "Close" : "Menu"}</span><svg viewBox="0 0 20 20" fill="none" aria-hidden="true">{mobileOpen ? <path d="m5 5 10 10M15 5 5 15" stroke="currentColor" strokeWidth="1.4" /> : <path d="M3 6h14M3 13h14" stroke="currentColor" strokeWidth="1.4" />}</svg>
          </button>
        </div>
      </header>
    </PublicNavigationContext.Provider>
  );
}
