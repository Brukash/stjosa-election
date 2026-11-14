"use client";

import { useEffect, useState } from "react";
import { Alert, Card, Loading, SectionHeading } from "@/components/ui";
import { api } from "@/lib/api";

type Enrollment = { secret: string; otpauth_url: string; instructions: string };

export default function SecurityPage() {
  const [me, setMe] = useState<any | null>(null);
  const [enrollment, setEnrollment] = useState<Enrollment | null>(null);
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  useEffect(() => {
    api("/api/auth/me", { auth: true })
      .then(setMe)
      .catch((err) => setError(err.message));
  }, []);

  async function startEnrollment() {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const data = await api("/api/auth/mfa/enroll", { method: "POST", auth: true });
      setEnrollment(data);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function activate(event: React.FormEvent) {
    event.preventDefault();
    if (!enrollment) return;
    setBusy(true);
    setError("");
    try {
      await api("/api/auth/mfa/activate", {
        method: "POST",
        auth: true,
        body: JSON.stringify({ secret: enrollment.secret, code: code.trim() }),
      });
      setMe({ ...me, mfa_enabled: true });
      setEnrollment(null);
      setCode("");
      setNotice("Two-factor authentication is now active for your account.");
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  if (!me && !error) return <Loading label="Loading account security…" />;

  return (
    <div className="space-y-5">
      <SectionHeading eyebrow="Account security" title="Two-factor authentication">
        Protect your election duties with a time-based code from an authenticator app in addition to
        your password.
      </SectionHeading>

      {error ? <Alert tone="error">{error}</Alert> : null}
      {notice ? <Alert tone="success">{notice}</Alert> : null}

      {me?.mfa_enabled ? (
        <Card className="card-pad">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="text-sm font-semibold text-ink">Two-factor authentication is active</p>
              <p className="mt-1 text-sm text-ink/55">
                Sign-in now requires your password and a current authenticator code.
              </p>
            </div>
            <span className="pill-green">Enabled</span>
          </div>
          <p className="mt-4 text-xs text-ink/45">
            If you lose access to your authenticator, contact the Super Administrator to reset it.
            Resets are recorded in the audit trail.
          </p>
        </Card>
      ) : enrollment ? (
        <Card className="card-pad">
          <p className="text-sm font-semibold text-ink">1. Add the account to your authenticator app</p>
          <p className="mt-1 text-sm text-ink/55">
            Choose “enter a setup key” in Google Authenticator, Authy, 1Password or a similar app, then
            enter this key:
          </p>
          <code className="code mt-3 block text-sm tracking-[0.2em]">{enrollment.secret}</code>
          <p className="mt-3 text-xs text-ink/45">
            Or open the setup link on the device with the authenticator app:{" "}
            <a href={enrollment.otpauth_url} className="font-semibold text-green underline">
              otpauth link
            </a>
          </p>

          <form onSubmit={activate} className="mt-6 max-w-sm">
            <p className="text-sm font-semibold text-ink">2. Confirm a generated code</p>
            <label className="label mt-3" htmlFor="code">
              Six-digit code
            </label>
            <input
              id="code"
              className="input font-mono tracking-[0.3em]"
              inputMode="numeric"
              maxLength={6}
              value={code}
              onChange={(event) => setCode(event.target.value.replace(/\D/g, ""))}
              placeholder="000000"
              required
            />
            <div className="mt-4 flex gap-2">
              <button className="btn-primary" disabled={busy || code.length !== 6}>
                {busy ? "Activating…" : "Activate two-factor"}
              </button>
              <button
                type="button"
                className="btn-ghost"
                onClick={() => {
                  setEnrollment(null);
                  setCode("");
                }}
              >
                Cancel
              </button>
            </div>
          </form>
        </Card>
      ) : (
        <Card className="card-pad">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="text-sm font-semibold text-ink">Two-factor authentication is not active</p>
              <p className="mt-1 text-sm text-ink/55">
                Enrol an authenticator app to protect accreditation, counting and result actions.
              </p>
            </div>
            <span className="pill-grey">Not enrolled</span>
          </div>
          <button className="btn-primary mt-5" onClick={startEnrollment} disabled={busy}>
            {busy ? "Preparing…" : "Set up authenticator"}
          </button>
        </Card>
      )}

      <Card className="card-pad">
        <p className="text-xs leading-relaxed text-ink/50">
          Your password is never stored in plain text, and authenticator codes are verified server-side.
          Every sign-in and MFA event is written to the election audit trail.
        </p>
      </Card>
    </div>
  );
}
