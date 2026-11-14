"use client";

import { useEffect, useState } from "react";
import { Alert, Card, Loading, SectionHeading } from "@/components/ui";
import { api, can, formatDate, getProfile } from "@/lib/api";

const BLANK = { email: "", full_name: "", password: "", roles: [] as string[] };

export default function TeamPage() {
  const profile = getProfile();
  const allowed = can(profile, "accounts.manage");
  const [catalogue, setCatalogue] = useState<any[]>([]);
  const [accounts, setAccounts] = useState<any[]>([]);
  const [drafts, setDrafts] = useState<Record<string, string[]>>({});
  const [form, setForm] = useState<any>(BLANK);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [resetFor, setResetFor] = useState<string>("");
  const [resetValue, setResetValue] = useState("");

  function load() {
    Promise.all([
      api("/api/accounts/roles", { auth: true }),
      allowed ? api("/api/accounts", { auth: true }) : Promise.resolve({ accounts: [] }),
    ])
      .then(([rolesData, accountsData]) => {
        setCatalogue(rolesData.roles);
        setAccounts(accountsData.accounts);
        const next: Record<string, string[]> = {};
        for (const account of accountsData.accounts) next[account.id] = account.roles;
        setDrafts(next);
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }

  useEffect(load, []);

  async function createAccount(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await api("/api/accounts", {
        method: "POST",
        auth: true,
        body: JSON.stringify({ ...form, roles: form.roles }),
      });
      setNotice(`Account created for ${form.email}. Share the password securely.`);
      setForm(BLANK);
      load();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function updateAccount(id: string, body: any, message: string) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await api(`/api/accounts/${id}`, {
        method: "PATCH",
        auth: true,
        body: JSON.stringify(body),
      });
      setNotice(message);
      setResetFor("");
      setResetValue("");
      load();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  function toggleRole(id: string, key: string) {
    setDrafts((current) => {
      const roles = current[id] ?? [];
      return {
        ...current,
        [id]: roles.includes(key) ? roles.filter((role) => role !== key) : [...roles, key],
      };
    });
  }

  if (loading) return <Loading label="Loading staff and roles…" />;

  const roleName = (key: string) => catalogue.find((role) => role.key === key)?.name ?? key;

  return (
    <div className="space-y-6">
      <SectionHeading eyebrow="Governance" title="Roles and access">
        Each official gets only the powers their office requires. Changes here are audited and take
        effect on the next request.
      </SectionHeading>

      {error ? <Alert tone="error">{error}</Alert> : null}
      {notice ? <Alert tone="success">{notice}</Alert> : null}
      {!allowed ? (
        <Alert tone="error">
          Your role cannot manage staff accounts. This page is restricted to the Super Administrator.
        </Alert>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-2">
        {catalogue.map((role) => (
          <Card key={role.key} className="card-pad">
            <div className="flex items-start justify-between gap-3">
              <h2 className="font-display text-lg text-ink">{role.name}</h2>
              <span className="pill-grey">{role.permissions.length} permissions</span>
            </div>
            <p className="mt-2 text-sm leading-relaxed text-ink/60">{role.description}</p>
            <details className="mt-3">
              <summary className="cursor-pointer text-xs font-semibold text-green">
                View permissions
              </summary>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {role.permissions.map((permission: string) => (
                  <span key={permission} className="code">
                    {permission}
                  </span>
                ))}
              </div>
            </details>
          </Card>
        ))}
      </div>

      {allowed ? (
        <>
          <Card className="card-pad">
            <SectionHeading eyebrow="Staff accounts" title="Officials with access" />
            <div className="space-y-4">
              {accounts.map((account) => (
                <div key={account.id} className="rounded-xl border border-line p-4">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <p className="text-sm font-semibold text-ink">
                        {account.full_name}
                        {account.id === profile?.id ? (
                          <span className="ml-2 text-[10px] uppercase tracking-wide text-green">You</span>
                        ) : null}
                      </p>
                      <p className="text-xs text-ink/50">{account.email}</p>
                      <p className="mt-1 text-[11px] text-ink/40">
                        Last sign-in {formatDate(account.last_login_at)} · MFA{" "}
                        {account.mfa_enabled ? "enabled" : "not enrolled"}
                      </p>
                    </div>
                    <span className={account.is_active ? "pill-green" : "pill-grey"}>
                      {account.is_active ? "Active" : "Disabled"}
                    </span>
                  </div>

                  <div className="mt-3 flex flex-wrap gap-3">
                    {catalogue.map((role) => (
                      <label key={role.key} className="flex items-center gap-2 text-xs text-ink/70">
                        <input
                          type="checkbox"
                          className="h-3.5 w-3.5 accent-green"
                          checked={(drafts[account.id] ?? []).includes(role.key)}
                          onChange={() => toggleRole(account.id, role.key)}
                        />
                        {role.name}
                      </label>
                    ))}
                  </div>

                  <div className="mt-3 flex flex-wrap gap-2">
                    <button
                      className="btn-outline !px-3 !py-1.5 text-xs"
                      disabled={busy || (drafts[account.id] ?? []).length === 0}
                      onClick={() =>
                        updateAccount(
                          account.id,
                          { roles: drafts[account.id] ?? [] },
                          `Roles updated for ${account.full_name}.`
                        )
                      }
                    >
                      Save roles
                    </button>
                    <button
                      className="btn-outline !px-3 !py-1.5 text-xs"
                      disabled={busy || account.id === profile?.id}
                      onClick={() =>
                        updateAccount(
                          account.id,
                          { is_active: !account.is_active },
                          account.is_active
                            ? `${account.full_name} has been disabled.`
                            : `${account.full_name} has been re-activated.`
                        )
                      }
                    >
                      {account.is_active ? "Disable account" : "Re-activate"}
                    </button>
                    <button
                      className="btn-ghost !px-3 !py-1.5 text-xs"
                      onClick={() => {
                        setResetFor(resetFor === account.id ? "" : account.id);
                        setResetValue("");
                      }}
                    >
                      Reset password
                    </button>
                  </div>

                  {resetFor === account.id ? (
                    <div className="mt-3 flex flex-wrap items-end gap-2">
                      <div className="min-w-[240px] flex-1">
                        <label className="label">New password (at least 12 characters)</label>
                        <input
                          type="password"
                          className="input"
                          value={resetValue}
                          onChange={(event) => setResetValue(event.target.value)}
                          autoComplete="new-password"
                        />
                      </div>
                      <button
                        className="btn-primary !px-3 !py-2 text-xs"
                        disabled={busy || resetValue.length < 12}
                        onClick={() =>
                          updateAccount(
                            account.id,
                            { password: resetValue },
                            `Password reset for ${account.full_name}. Existing sessions remain valid until they expire.`
                          )
                        }
                      >
                        Set password
                      </button>
                    </div>
                  ) : null}

                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {account.roles.map((key: string) => (
                      <span key={key} className="pill-green">
                        {roleName(key)}
                      </span>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </Card>

          <Card className="card-pad">
            <SectionHeading eyebrow="New account" title="Add an official" />
            <form onSubmit={createAccount} className="grid gap-4 sm:grid-cols-2">
              <div>
                <label className="label">Full name</label>
                <input
                  className="input"
                  value={form.full_name}
                  onChange={(event) => setForm({ ...form, full_name: event.target.value })}
                  required
                />
              </div>
              <div>
                <label className="label">Official email</label>
                <input
                  type="email"
                  className="input"
                  value={form.email}
                  onChange={(event) => setForm({ ...form, email: event.target.value })}
                  required
                />
              </div>
              <div className="sm:col-span-2">
                <label className="label">Initial password (at least 12 characters)</label>
                <input
                  type="password"
                  className="input"
                  value={form.password}
                  onChange={(event) => setForm({ ...form, password: event.target.value })}
                  autoComplete="new-password"
                  minLength={12}
                  required
                />
              </div>
              <div className="sm:col-span-2">
                <label className="label">Roles</label>
                <div className="flex flex-wrap gap-3">
                  {catalogue.map((role) => (
                    <label key={role.key} className="flex items-center gap-2 text-sm text-ink/70">
                      <input
                        type="checkbox"
                        className="h-4 w-4 accent-green"
                        checked={form.roles.includes(role.key)}
                        onChange={() =>
                          setForm({
                            ...form,
                            roles: form.roles.includes(role.key)
                              ? form.roles.filter((key: string) => key !== role.key)
                              : [...form.roles, role.key],
                          })
                        }
                      />
                      {role.name}
                    </label>
                  ))}
                </div>
              </div>
              <div className="sm:col-span-2">
                <button
                  className="btn-primary"
                  disabled={busy || form.roles.length === 0 || form.password.length < 12}
                >
                  {busy ? "Creating…" : "Create account"}
                </button>
              </div>
            </form>
          </Card>
        </>
      ) : null}
    </div>
  );
}
