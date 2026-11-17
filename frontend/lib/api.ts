export const API_BASE =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") ?? "http://127.0.0.1:8000";

const TOKEN_KEY = "sjc_staff_token";
const PROFILE_KEY = "sjc_staff_profile";

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

// fetch() rejects with a bare "Failed to fetch" when the API is unreachable,
// the origin is not allowed, or the network is down. That sentence is not
// something a voter can act on, so it never reaches the page.
export const NETWORK_ERROR_MESSAGE =
  "We could not reach the election service. Check your connection and try again.";
const UNREADABLE_RESPONSE_MESSAGE =
  "The election service sent an unreadable response. Please try again.";

function statusMessage(status: number): string {
  return status >= 500
    ? `The election service had a problem (${status}). Please try again in a moment.`
    : `That request could not be completed (${status}). Please try again.`;
}

async function send(url: string, init: RequestInit): Promise<Response> {
  try {
    return await fetch(url, init);
  } catch {
    throw new ApiError(NETWORK_ERROR_MESSAGE, 0);
  }
}

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_KEY);
}

export function getProfile(): any | null {
  if (typeof window === "undefined") return null;
  const raw = window.localStorage.getItem(PROFILE_KEY);
  try {
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

export function saveSession(token: string, profile: any) {
  window.localStorage.setItem(TOKEN_KEY, token);
  window.localStorage.setItem(PROFILE_KEY, JSON.stringify(profile));
}

export function clearSession() {
  window.localStorage.removeItem(TOKEN_KEY);
  window.localStorage.removeItem(PROFILE_KEY);
}

export function can(profile: any, permission: string): boolean {
  return Array.isArray(profile?.permissions) && profile.permissions.includes(permission);
}

export async function api<T = any>(
  path: string,
  options: RequestInit & { auth?: boolean } = {}
): Promise<T> {
  const { auth = false, headers, ...rest } = options;
  const finalHeaders: Record<string, string> = {
    "Content-Type": "application/json",
    ...(headers as Record<string, string>),
  };
  if (auth) {
    const token = getToken();
    if (token) finalHeaders.Authorization = `Bearer ${token}`;
  }
  const response = await send(`${API_BASE}${path}`, {
    ...rest,
    headers: finalHeaders,
    cache: "no-store",
  });
  const isJson = (response.headers.get("content-type") ?? "").includes("application/json");
  let body: any;
  try {
    body = isJson ? await response.json() : await response.text();
  } catch {
    throw new ApiError(UNREADABLE_RESPONSE_MESSAGE, response.status);
  }
  if (!response.ok) {
    const detail =
      typeof body === "object" && body?.detail
        ? typeof body.detail === "string"
          ? body.detail
          : JSON.stringify(body.detail)
        : statusMessage(response.status);
    throw new ApiError(detail, response.status);
  }
  return body as T;
}

export async function downloadWithAuth(path: string, filename: string): Promise<void> {
  const token = getToken();
  const response = await send(`${API_BASE}${path}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    cache: "no-store",
  });
  if (!response.ok) {
    const message = await response.text().catch(() => "");
    throw new ApiError(message || statusMessage(response.status), response.status);
  }
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

export function formatDate(value?: string | null, withTime = true): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString("en-GB", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    ...(withTime ? { hour: "2-digit", minute: "2-digit" } : {}),
  });
}

// Voter-facing dates are shown in the election's own time zone with a plain
// 12-hour clock, so "closes" reads the same in Lagos and abroad.
export function formatLongDate(value?: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  const day = date.toLocaleDateString("en-GB", {
    day: "numeric",
    month: "long",
    year: "numeric",
    timeZone: "Africa/Lagos",
  });
  const time = date.toLocaleTimeString("en-GB", {
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
    timeZone: "Africa/Lagos",
  });
  return `${day}, ${time} WAT`;
}

export function toDateTimeInput(value?: string | null): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(
    date.getHours()
  )}:${pad(date.getMinutes())}`;
}

export function fromDateTimeInput(value: string): string | null {
  if (!value) return null;
  return new Date(value).toISOString();
}

export function shortHash(value?: string | null, size = 10): string {
  if (!value) return "—";
  return value.length > size * 2 ? `${value.slice(0, size)}…${value.slice(-size)}` : value;
}
