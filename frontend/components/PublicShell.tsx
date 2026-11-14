"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { ReactNode } from "react";

const NAV = [
  { href: "/", label: "Home" },
  { href: "/accredit", label: "Accredit & Vote" },
  { href: "/verify", label: "Verify" },
  { href: "/commitments", label: "Commitments" },
  { href: "/results", label: "Results" },
];

export function Crest({ size = 40 }: { size?: number }) {
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src="/Josa.png"
      alt="St. John's College Jos crest"
      width={Math.round(size * (438 / 557))}
      height={size}
      className="shrink-0 rounded-md bg-white object-contain"
    />
  );
}

export function PublicShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  return (
    <div className="flex min-h-screen flex-col">
      <header className="sticky top-0 z-30 border-b border-line/80 bg-cream/90 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-4 py-3.5 sm:px-6">
          <Link href="/" className="flex items-center gap-3">
            <Crest size={46} />
            <span className="leading-tight">
              <span className="block font-display text-sm text-ink sm:text-base">
                St. John&apos;s College Jos
              </span>
              <span className="block text-[10px] font-semibold uppercase tracking-[0.16em] text-ink/45">
                Alumni Election Management
              </span>
            </span>
          </Link>
          <nav className="hidden items-center gap-1 lg:flex">
            {NAV.map((item) => {
              const active = pathname === item.href;
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={`rounded-lg px-3 py-2 text-[13px] font-medium transition ${
                    active ? "bg-ink text-white" : "text-ink/65 hover:bg-ink/5 hover:text-ink"
                  }`}
                >
                  {item.label}
                </Link>
              );
            })}
          </nav>
          <Link href="/admin" className="btn-outline !px-3 !py-2 text-[13px]">
            Admin portal
          </Link>
        </div>
        <div className="flex gap-1 overflow-x-auto px-4 pb-2 lg:hidden">
          {NAV.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className={`whitespace-nowrap rounded-lg px-2.5 py-1.5 text-xs font-medium ${
                pathname === item.href ? "bg-ink text-white" : "text-ink/60"
              }`}
            >
              {item.label}
            </Link>
          ))}
        </div>
      </header>
      <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-8 sm:px-6 sm:py-10">{children}</main>
      <footer className="border-t border-line bg-white">
        <div className="mx-auto flex max-w-6xl flex-col gap-3 px-4 py-7 text-xs text-ink/45 sm:flex-row sm:items-center sm:justify-between sm:px-6">
          <p>
            © {new Date().getFullYear()} St. John&apos;s College Jos Alumni Association · Electoral
            Committee
          </p>
          <p>
            Every eligible alumnus can vote once, verify their ballot, and check the declared result.
          </p>
        </div>
      </footer>
    </div>
  );
}
