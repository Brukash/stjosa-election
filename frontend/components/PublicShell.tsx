"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { ReactNode, useCallback, useEffect, useRef, useState } from "react";

const NAV = [
  { href: "/", label: "Home" },
  { href: "/accredit", label: "Vote" },
  { href: "/results", label: "Results" },
  { href: "/verify", label: "Verify" },
];

// The record page is only surfaced in the menu and the footer.
const MENU_NAV = [...NAV, { href: "/commitments", label: "Ballot commitments" }];

function isActive(pathname: string, href: string) {
  return href === "/" ? pathname === "/" : pathname === href || pathname.startsWith(`${href}/`);
}

export function Crest({ size = 40 }: { size?: number }) {
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src="/Josa.png"
      alt=""
      width={Math.round(size * (438 / 557))}
      height={size}
      className="shrink-0 rounded-[3px] object-contain"
    />
  );
}

function Wordmark() {
  return (
    <span className="min-w-0 leading-tight">
      <span className="block font-display text-[15px] leading-snug text-ink sm:text-[17px]">
        St. John&apos;s College Jos
      </span>
      <span className="mt-0.5 block text-[10px] font-semibold uppercase tracking-eyebrow text-ink/55">
        Alumni Association
      </span>
    </span>
  );
}

/** Mounted only while open, so it owns the Escape key, scroll lock and focus. */
function MobilePanel({ pathname, onClose }: { pathname: string; onClose: () => void }) {
  const panelRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    panelRef.current?.querySelector<HTMLAnchorElement>("a")?.focus();
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = previous;
    };
  }, [onClose]);

  return (
    <div
      id="mobile-nav"
      ref={panelRef}
      className="border-t border-rule bg-surface px-4 pb-5 pt-3 lg:hidden"
    >
      <nav aria-label="Voter navigation" className="flex flex-col">
        {MENU_NAV.map((item) => {
          const active = isActive(pathname, item.href);
          return (
            <Link
              key={item.href}
              href={item.href}
              aria-current={active ? "page" : undefined}
              className={`flex min-h-[48px] items-center justify-between border-b border-rule/70 text-[15px] ${
                active ? "font-semibold text-forest" : "text-ink/80"
              }`}
            >
              {item.label}
              <span aria-hidden="true" className="text-ink/30">
                →
              </span>
            </Link>
          );
        })}
        <Link
          href="/admin"
          className="mt-4 flex min-h-[48px] items-center justify-center rounded-[6px] bg-forest px-4 text-[14px] font-semibold text-white"
        >
          Committee sign-in
        </Link>
      </nav>
    </div>
  );
}

export function PublicShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const close = useCallback(() => setOpen(false), []);

  useEffect(() => {
    setOpen(false);
  }, [pathname]);

  return (
    <div className="flex min-h-screen flex-col">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-[6px] focus:bg-forest focus:px-4 focus:py-2 focus:text-sm focus:text-white"
      >
        Skip to content
      </a>

      <header className="sticky top-0 z-40 border-b border-rule bg-paper/95 backdrop-blur supports-[backdrop-filter]:bg-paper/85">
        <div className="mx-auto flex max-w-6xl items-center gap-3 px-4 py-3 sm:px-6">
          <Link
            href="/"
            className="flex min-w-0 items-center gap-3"
            aria-label="St. John's College Jos Alumni Election, home"
          >
            <Crest size={38} />
            <Wordmark />
          </Link>

          <nav className="ml-auto hidden items-center gap-1 lg:flex" aria-label="Voter navigation">
            {NAV.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                aria-current={isActive(pathname, item.href) ? "page" : undefined}
                className={`rounded-[5px] px-3 py-2 text-[13.5px] font-medium transition ${
                  isActive(pathname, item.href)
                    ? "text-forest underline decoration-ochre decoration-2 underline-offset-[6px]"
                    : "text-ink/70 hover:text-ink"
                }`}
              >
                {item.label}
              </Link>
            ))}
            <Link
              href="/admin"
              className="ml-2 rounded-[5px] border border-ink/20 px-3 py-2 text-[13px] font-medium text-ink/70 transition hover:border-ink/45 hover:text-ink"
            >
              Committee sign-in
            </Link>
          </nav>

          <button
            type="button"
            onClick={() => setOpen((value) => !value)}
            aria-expanded={open}
            aria-controls="mobile-nav"
            className="ml-auto inline-flex min-h-[44px] min-w-[44px] items-center justify-center gap-2 rounded-[6px] border border-ink/20 px-3 text-[13px] font-semibold text-ink lg:hidden"
          >
            <span aria-hidden="true" className="flex flex-col gap-[3px]">
              <span className="block h-[1.5px] w-4 bg-ink" />
              <span className="block h-[1.5px] w-4 bg-ink" />
              <span className="block h-[1.5px] w-4 bg-ink" />
            </span>
            Menu
          </button>
        </div>

        {open ? <MobilePanel pathname={pathname} onClose={close} /> : null}
      </header>

      <main id="main" className="mx-auto w-full max-w-6xl flex-1 px-4 py-8 sm:px-6 sm:py-12">
        {children}
      </main>

      <footer className="border-t border-rule bg-surface">
        <div className="mx-auto max-w-6xl px-4 py-10 sm:px-6">
          <div className="grid gap-8 sm:grid-cols-2 lg:grid-cols-4">
            <div className="lg:col-span-2">
              <div className="flex items-center gap-3">
                <Crest size={34} />
                <Wordmark />
              </div>
              <p className="measure mt-3 text-[13px] leading-relaxed text-ink/60">
                Conducted by the Electoral Committee of the St. John&apos;s College Jos Alumni
                Association. Every eligible alumnus can vote once and check that their ballot was
                recorded.
              </p>
            </div>

            <div>
              <p className="eyebrow">Voting</p>
              <ul className="mt-3 space-y-2 text-[13px] text-ink/70">
                <li><Link className="link-rule hover:text-forest" href="/accredit">Accredit and vote</Link></li>
                <li><Link className="link-rule hover:text-forest" href="/verify">Check a ballot</Link></li>
                <li><Link className="link-rule hover:text-forest" href="/results">Declared results</Link></li>
              </ul>
            </div>

            <div>
              <p className="eyebrow">The record</p>
              <ul className="mt-3 space-y-2 text-[13px] text-ink/70">
                <li><Link className="link-rule hover:text-forest" href="/commitments">Ballot commitments</Link></li>
                <li>
                  <a className="link-rule hover:text-forest" href="mailto:accreditation@sjcjos-alumni.org">
                    accreditation@sjcjos-alumni.org
                  </a>
                </li>
                <li><Link className="link-rule hover:text-forest" href="/admin">Committee sign-in</Link></li>
              </ul>
            </div>
          </div>

          <div className="mt-8 flex flex-col gap-2 border-t border-rule pt-5 text-[11px] text-ink/50 sm:flex-row sm:items-center sm:justify-between">
            <p>© {new Date().getFullYear()} St. John&apos;s College Jos Alumni Association</p>
            <p>Electoral Committee · Remote electronic ballot</p>
          </div>
        </div>
      </footer>
    </div>
  );
}
