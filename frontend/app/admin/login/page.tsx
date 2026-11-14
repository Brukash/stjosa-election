"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Crest } from "@/components/PublicShell";
import { Alert, Card } from "@/components/ui";
import { api, saveSession } from "@/lib/api";

export default function AdminLoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [totp, setTotp] = useState("");
  const [needsMfa, setNeedsMfa] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const data = await api("/api/auth/login", {
        method: "POST",
        body: JSON.stringify({
          email: email.trim(),
          password,
          ...(totp ? { totp_code: totp.trim() } : {}),
        }),
      });
      saveSession(data.access_token, data.profile);
      router.replace("/admin");
    } catch (err: any) {
      if (err.message?.toLowerCase().includes("mfa")) setNeedsMfa(true);
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-ink px-4 py-10">
      <div className="w-full max-w-md">
        <div className="mb-6 flex items-center gap-3 text-white">
          <Crest size={46} />
          <div>
            <p className="font-display text-lg">St. John&apos;s College Jos</p>
            <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-white/50">
              Alumni Election Control Room
            </p>
          </div>
        </div>
        <Card className="card-pad">
          <h1 className="font-display text-xl text-ink">Authorised staff sign in</h1>
          <p className="mt-1 text-sm text-ink/55">
            Access is restricted to Electoral Committee officials, observers and technical
            administrators. All sign-in attempts are audited.
          </p>

          {error ? <div className="mt-4"><Alert tone="error">{error}</Alert></div> : null}

          <form onSubmit={submit} className="mt-5 space-y-4">
            <div>
              <label className="label" htmlFor="email">
                Official email
              </label>
              <input
                id="email"
                type="email"
                className="input"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                autoComplete="username"
                required
              />
            </div>
            <div>
              <label className="label" htmlFor="password">
                Password
              </label>
              <input
                id="password"
                type="password"
                className="input"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                autoComplete="current-password"
                required
              />
            </div>
            {needsMfa ? (
              <div>
                <label className="label" htmlFor="totp">
                  Authenticator code
                </label>
                <input
                  id="totp"
                  className="input font-mono tracking-[0.3em]"
                  inputMode="numeric"
                  maxLength={6}
                  value={totp}
                  onChange={(event) => setTotp(event.target.value.replace(/\D/g, ""))}
                  placeholder="000000"
                />
              </div>
            ) : null}
            <button className="btn-primary w-full" disabled={busy}>
              {busy ? "Signing in…" : "Sign in"}
            </button>
          </form>

          <p className="mt-4 text-xs text-ink/45">
            MFA can be enrolled after signing in.{" "}
            <Link href="/" className="font-semibold text-green underline">
              Return to public site
            </Link>
          </p>
        </Card>
        <p className="mt-4 text-center text-[11px] text-white/35">
          Demo accounts are documented in the project README.
        </p>
      </div>
    </div>
  );
}
