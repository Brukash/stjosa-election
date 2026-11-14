"use client";

import { useEffect, useState } from "react";
import { Alert, Card, Loading, SectionHeading, Stat } from "@/components/ui";
import { api } from "@/lib/api";

export default function DeliverySettingsPage() {
  const [data, setData] = useState<any | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api("/api/settings/delivery", { auth: true })
      .then(setData)
      .catch((err) => setError(err.message));
  }, []);

  if (!data && !error) return <Loading label="Loading delivery configuration…" />;

  return (
    <div className="space-y-5">
      <SectionHeading eyebrow="Technical settings" title="OTP delivery providers">
        The Super Administrator manages provider credentials in the server-side environment or
        deployment secret store. Secrets are never editable here, returned by the API, or stored in
        the browser.
      </SectionHeading>

      {error ? <Alert tone="error">{error}</Alert> : null}

      {data ? (
        <>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Stat label="Environment" value={data.environment} />
            <Stat label="OTP length" value={`${data.otp.length} digits`} />
            <Stat label="Validity" value={`${Math.round(data.otp.ttl_seconds / 60)} min`} />
            <Stat label="Attempt / resend" value={`${data.otp.max_attempts} / ${data.otp.resend_seconds}s`} />
          </div>

          <div className="grid gap-4 lg:grid-cols-3">
            {data.providers.map((provider: any) => (
              <Card key={provider.channel} className="card-pad">
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-ink/40">
                      {provider.channel}
                    </p>
                    <h2 className="mt-1 font-display text-lg text-ink">{provider.label}</h2>
                  </div>
                  <span className={provider.configured ? "pill-green" : "pill-grey"}>
                    {provider.configured ? "Ready" : "Not configured"}
                  </span>
                </div>
                <p className="mt-2 text-xs text-ink/50">
                  Provider: <span className="font-mono">{provider.provider}</span>
                </p>
                <p className="mt-4 text-[11px] font-semibold uppercase tracking-wide text-ink/40">
                  Required server variables
                </p>
                <ul className="mt-1.5 space-y-1">
                  {provider.required_settings.map((name: string) => (
                    <li key={name} className="code block text-[11px]">{name}</li>
                  ))}
                </ul>
                {provider.channel === "whatsapp" ? (
                  <div className="mt-4 space-y-1 border-t border-line pt-3 text-[11px] text-ink/55">
                    <p>Template: <span className="font-mono">{provider.template}</span></p>
                    <p>Language: <span className="font-mono">{provider.template_language}</span></p>
                    <p>Consent is required for every voter before WhatsApp is offered.</p>
                    <p className="break-all">
                      Webhook: <span className="font-mono">{provider.delivery_status_webhook?.url}</span>
                    </p>
                    <p>
                      Signed webhook:{" "}
                      <strong>{provider.delivery_status_webhook?.signature_configured ? "yes" : "no"}</strong>
                    </p>
                  </div>
                ) : null}
              </Card>
            ))}
          </div>

          <Card className="card-pad">
            <SectionHeading eyebrow="Controls" title="Accreditation limits">
              These limits are enforced server-side for every challenge and resend.
            </SectionHeading>
            <dl className="space-y-1">
              <div className="kv">
                <dt>Resend cooldown</dt>
                <dd>{data.otp.resend_seconds} seconds</dd>
              </div>
              <div className="kv">
                <dt>Maximum requests per voter / hour</dt>
                <dd>{data.otp.max_requests_per_hour}</dd>
              </div>
              <div className="kv">
                <dt>Maximum incorrect attempts</dt>
                <dd>{data.otp.max_attempts} per challenge</dd>
              </div>
              <div className="kv">
                <dt>WhatsApp platform</dt>
                <dd>{data.whatsapp.official_platform}</dd>
              </div>
              <div className="kv">
                <dt>WhatsApp consent</dt>
                <dd>Required and recorded on the electoral register</dd>
              </div>
              <div className="kv">
                <dt>Webhook signature</dt>
                <dd>{data.whatsapp.webhook_signed ? "Enabled" : "Set WHATSAPP_APP_SECRET"}</dd>
              </div>
            </dl>
            <Alert tone="info">
              {data.security_note} After changing provider variables, restart or redeploy the API.
              Verify the sender domain, SMS sender and Meta template before an official election.
            </Alert>
          </Card>
        </>
      ) : null}
    </div>
  );
}
