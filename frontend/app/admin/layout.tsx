"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Crest } from "@/components/PublicShell";
import { NotAuthorized } from "@/components/ui";
import {
  api,
  clearSession,
  getProfile,
  getToken,
  refreshSession,
  saveSession,
  SESSION_EXPIRED_EVENT,
  tokenExpiresAt,
} from "@/lib/api";

const NAV = [
  { href: "/admin", label: "Monitoring", permission: "monitor.view" },
  { href: "/admin/accreditation", label: "Accreditation", permission: "accreditation.oversight" },
  { href: "/admin/elections", label: "Elections", permission: "election.view" },
  { href: "/admin/security", label: "Security", permission: "election.view" },
  { href: "/admin/delivery", label: "Delivery", permission: "technical.settings" },
  { href: "/admin/team", label: "Team & roles", permission: "accounts.manage" },
];

// A section stays highlighted while a deeper page in it is open, so the tab
// bar never looks like no section is active.
function isSectionActive(pathname: string, href: string): boolean {
  if (href === "/admin") return pathname === "/admin";
  return pathname === href || pathname.startsWith(`${href}/`);
}

// Direct URL access is checked against the same permissions that render the navigation.
// The API remains the authority; this prevents a hidden page from opening via a typed URL.
function requiredPermissions(pathname: string): string[] | null {
  const segments = pathname.split("/").filter(Boolean);
  if (segments[0] !== "admin") return null;
  if (segments[1] === "team") return ["accounts.manage"];
  if (segments[1] === "delivery") return ["technical.settings"];
  if (segments[1] === "accreditation") return ["accreditation.oversight"];
  if (segments[1] === "elections" && segments[3]) {
    const tab = segments[3];
    if (tab === "register") return ["register.view"];
    if (tab === "counting") return ["counting.authorise"];
    if (tab === "results") return ["results.review", "results.review_restricted"];
    if (tab === "audit") return ["audit.view", "audit.view_technical"];
  }
  return null;
}

// A polling day runs around the clock, so an officer may stay signed in for a
// full 24 hours. The token is renewed in the background whenever less than four
// hours remain, which is well before expiry, so a working session never ends in
// a surprise sign-out. If the browser is closed long enough for the token to
// lapse, signing in returns the officer to the exact page they were working on.
const RENEW_BEFORE_MS = 4 * 60 * 60 * 1000;
const RENEW_CHECK_MS = 10 * 60 * 1000;

function currentPath(): string {
  if (typeof window === "undefined") return "/admin";
  return `${window.location.pathname}${window.location.search}`;
}

function loginPath(next: string): string {
  return `/admin/login?next=${encodeURIComponent(next)}`;
}

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [profile, setProfile] = useState<any | null>(null);
  const [checked, setChecked] = useState(false);
  const isLogin = pathname === "/admin/login";

  // A rejected token is handled in one place: drop the session and send the
  // officer back to sign in, still pointing at the page they were using.
  useEffect(() => {
    if (isLogin) return;
    const onExpired = () => {
      clearSession();
      router.replace(loginPath(currentPath()));
    };
    window.addEventListener(SESSION_EXPIRED_EVENT, onExpired);
    return () => window.removeEventListener(SESSION_EXPIRED_EVENT, onExpired);
  }, [isLogin, router]);

  useEffect(() => {
    if (isLogin) {
      setChecked(true);
      return;
    }
    if (!getToken()) {
      router.replace(loginPath(currentPath()));
      return;
    }
    let cancelled = false;
    api("/api/auth/me", { auth: true })
      .then((me) => {
        if (cancelled) return;
        saveSession(getToken() as string, me);
        setProfile(me);
        setChecked(true);
      })
      .catch((err: any) => {
        if (cancelled) return;
        // Only an authentication failure ends the session. A dropped network or
        // a 5xx during the count must not sign an officer out mid-election.
        if (!(err?.status === 401 || err?.status === 403)) {
          const cached = getProfile();
          if (cached) {
            setProfile(cached);
            setChecked(true);
            return;
          }
        }
        clearSession();
        router.replace(loginPath(currentPath()));
      });
    return () => {
      cancelled = true;
    };
  }, [isLogin, pathname, router]);

  // Keeps a long shift alive: a check on entry, every ten minutes, and whenever
  // the tab is brought back after the laptop slept.
  useEffect(() => {
    if (isLogin || !checked || !profile) return;
    let stopped = false;
    const renew = async () => {
      const expiresAt = tokenExpiresAt(getToken());
      if (expiresAt === null || expiresAt - Date.now() > RENEW_BEFORE_MS) return;
      try {
        const me = await refreshSession();
        if (!stopped) setProfile(me);
      } catch {
        // The next check retries; a dead token already sends the officer to sign in.
      }
    };
    void renew();
    const timer = window.setInterval(() => void renew(), RENEW_CHECK_MS);
    const onVisible = () => {
      if (document.visibilityState === "visible") void renew();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      stopped = true;
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [isLogin, checked, profile]);

  if (isLogin) return <>{children}</>;

  if (!checked || !profile) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-paper text-sm text-ink/50">
        Checking your session…
      </div>
    );
  }

  const permissions: string[] = profile.permissions ?? [];
  const required = requiredPermissions(pathname);
  const authorized = !required || required.some((permission) => permissions.includes(permission));
  const roleNames: string[] = profile.role_names?.length
    ? profile.role_names
    : profile.roles ?? [];

  return (
    <div className="min-h-screen bg-paper">
      <a
        href="#admin-main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-[6px] focus:bg-forest focus:px-4 focus:py-2 focus:text-sm focus:text-white"
      >
        Skip to content
      </a>
      <header className="sticky top-0 z-30 border-b border-rule bg-white/95 backdrop-blur supports-[backdrop-filter]:bg-white/90">
        <div className="mx-auto max-w-6xl px-4 sm:px-6">
          <div className="flex items-center gap-3 py-2.5 sm:py-3">
            <Crest size={38} />
            <div className="min-w-0 flex-1">
              <p className="hidden truncate text-[9.5px] font-semibold uppercase tracking-[0.2em] text-[#7A4F14] sm:block">
                Electoral Committee
              </p>
              <p className="truncate font-display text-[16px] leading-tight text-ink sm:text-[18px]">
                Election Control Room
              </p>
              <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1">
                <p className="truncate text-[10.5px] text-ink/55 sm:text-[11.5px]">
                  <span className="font-semibold text-ink">{profile.full_name}</span>
                </p>
                {roleNames.length ? (
                  roleNames.map((role: string) => (
                    <span
                      key={role}
                      className="whitespace-nowrap rounded-full border border-ochre/35 bg-ochre/[0.09] px-2 py-[3px] text-[8.5px] font-semibold uppercase tracking-[0.1em] text-[#7A4F14] sm:text-[9px]"
                    >
                      {role}
                    </span>
                  ))
                ) : (
                  <span className="pill-grey">No role assigned</span>
                )}
              </div>
            </div>
            <div className="flex shrink-0 items-center gap-1 sm:gap-2">
              <Link
                href="/"
                className="hidden min-h-[36px] items-center rounded-[5px] px-2 text-[11.5px] font-medium text-ink/55 transition hover:bg-ink/[0.04] hover:text-ink sm:inline-flex"
              >
                Public site <span aria-hidden="true" className="ml-1 text-ink/35">↗</span>
              </Link>
              <button
                className="inline-flex min-h-[44px] items-center rounded-[5px] border border-ink/20 px-2.5 text-[11.5px] font-semibold text-ink/75 transition hover:border-ink/45 hover:text-ink sm:min-h-[40px] sm:px-3"
                onClick={() => {
                  const returnTo = currentPath();
                  clearSession();
                  router.replace(loginPath(returnTo));
                }}
              >
                Sign out
              </button>
            </div>
          </div>
        </div>
        <nav
          aria-label="Control room sections"
          className="mx-auto flex max-w-6xl items-stretch gap-0.5 overflow-x-auto border-t border-rule/70 px-4 [scrollbar-width:none] sm:px-6 [&::-webkit-scrollbar]:hidden"
        >
          {NAV.filter((item) => permissions.includes(item.permission)).map((item) => {
            const active = isSectionActive(pathname, item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                aria-current={active ? "page" : undefined}
                className={`group relative flex min-h-[44px] shrink-0 items-center whitespace-nowrap px-2.5 text-[12.5px] transition first:pl-0 sm:min-h-[42px] sm:px-3 sm:first:pl-0 sm:text-[13px] ${
                  active ? "font-semibold text-ink" : "font-medium text-ink/60 hover:text-ink"
                }`}
              >
                {item.label}
                <span
                  aria-hidden="true"
                  className={`absolute inset-x-0 bottom-0 h-[2px] rounded-t-full transition-opacity duration-200 ${
                    active ? "bg-ochre" : "bg-ink/25 opacity-0 group-hover:opacity-100"
                  }`}
                />
              </Link>
            );
          })}
          <span className="ml-auto hidden shrink-0 items-center gap-1.5 pl-6 text-[9px] font-semibold uppercase tracking-[0.14em] text-ink/30 lg:flex">
            <span className="h-1.5 w-1.5 rounded-full bg-green" />
            Secure session
          </span>
        </nav>
      </header>
      <main id="admin-main" className="mx-auto w-full max-w-6xl px-4 py-6 sm:px-6 sm:py-8">
        {authorized ? (
          children
        ) : (
          <NotAuthorized
            roleNames={profile.role_names ?? []}
            backHref={permissions.includes("monitor.view") ? "/admin" : "/admin/elections"}
          />
        )}
      </main>
    </div>
  );
}
