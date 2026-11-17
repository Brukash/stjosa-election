"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Crest } from "@/components/PublicShell";
import { NotAuthorized } from "@/components/ui";
import { api, clearSession, getToken, saveSession } from "@/lib/api";

const NAV = [
  { href: "/admin", label: "Monitoring", permission: "monitor.view" },
  { href: "/admin/accreditation", label: "Accreditation", permission: "accreditation.oversight" },
  { href: "/admin/elections", label: "Elections", permission: "election.view" },
  { href: "/admin/security", label: "Security", permission: "election.view" },
  { href: "/admin/delivery", label: "Delivery", permission: "technical.settings" },
  { href: "/admin/team", label: "Team & roles", permission: "accounts.manage" },
];

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

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [profile, setProfile] = useState<any | null>(null);
  const [checked, setChecked] = useState(false);
  const isLogin = pathname === "/admin/login";

  useEffect(() => {
    if (isLogin) {
      setChecked(true);
      return;
    }
    if (!getToken()) {
      router.replace("/admin/login");
      return;
    }
    api("/api/auth/me", { auth: true })
      .then((me) => {
        saveSession(getToken() as string, me);
        setProfile(me);
        setChecked(true);
      })
      .catch(() => {
        clearSession();
        router.replace("/admin/login");
      });
  }, [isLogin, pathname, router]);

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
      <header className="sticky top-0 z-30 border-b border-rule bg-white/95 shadow-sm backdrop-blur">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-3 px-4 py-3 sm:px-6">
          <div className="flex items-center gap-3">
            <Crest size={34} />
            <div className="leading-tight">
              <p className="font-display text-sm text-ink">Election Control Room</p>
              <p className="mt-0.5 text-[11px] font-medium text-ink/60">
                Signed in as <span className="font-semibold text-ink">{profile.full_name}</span>
              </p>
              <div className="mt-1 flex flex-wrap items-center gap-1.5">
                <span className="text-[9px] font-semibold uppercase tracking-[0.14em] text-ink/40">
                  Role
                </span>
                {roleNames.length ? (
                  roleNames.map((role: string) => (
                    <span
                      key={role}
                      className="rounded-full border border-green/20 bg-green/[0.08] px-2 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-green"
                    >
                      {role}
                    </span>
                  ))
                ) : (
                  <span className="pill-grey">No role assigned</span>
                )}
              </div>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Link href="/" className="btn-ghost text-xs">
              Public site
            </Link>
            <button
              className="btn-outline !px-3 !py-2 text-xs"
              onClick={() => {
                clearSession();
                router.replace("/admin/login");
              }}
            >
              Sign out
            </button>
          </div>
        </div>
        <div className="mx-auto flex max-w-6xl gap-1 overflow-x-auto px-4 pb-2 sm:px-6">
          {NAV.filter((item) => permissions.includes(item.permission)).map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className={`whitespace-nowrap rounded-lg px-3 py-1.5 text-[13px] font-medium ${
                pathname === item.href ? "bg-ink text-white" : "text-ink/60 hover:bg-ink/5"
              }`}
            >
              {item.label}
            </Link>
          ))}
          <span className="ml-auto hidden items-center gap-1.5 self-center text-[10px] uppercase tracking-wide text-ink/35 sm:flex">
            <span className="h-1.5 w-1.5 rounded-full bg-green" />
            Authenticated session
          </span>
        </div>
      </header>
      <main className="mx-auto w-full max-w-6xl px-4 py-6 sm:px-6 sm:py-8">
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
