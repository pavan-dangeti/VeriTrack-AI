/**
 * Same-origin `/api/v1` by default (Vite proxy in dev, Vercel rewrite in prod) so the refresh
 * cookie stays first-party. Set VITE_API_BASE_URL only for a cross-origin API.
 */
export const API_BASE = `${(import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "")}/api/v1`;
const BASE = API_BASE;

let accessToken: string | null = null;
let refreshHandler: (() => Promise<boolean>) | null = null;

export function setAccessToken(token: string | null) {
  accessToken = token;
}

/**
 * Refresh tokens rotate and a replayed one revokes the whole session family,
 * so concurrent 401s must share ONE refresh call — never race several.
 */
export function setRefreshHandler(fn: () => Promise<boolean>) {
  let inflight: Promise<boolean> | null = null;
  refreshHandler = () => {
    inflight ??= fn().finally(() => {
      inflight = null;
    });
    return inflight;
  };
}

export class ApiError extends Error {
  public readonly status: number;
  public readonly code: string;
  public readonly requestId: string | null;

  constructor(status: number, code: string, message: string, requestId: string | null = null) {
    super(message);
    this.status = status;
    this.code = code;
    this.requestId = requestId;
  }
}

async function raw(path: string, init?: RequestInit): Promise<Response> {
  const headers: Record<string, string> = {
    ...(init?.headers as Record<string, string>),
    "X-Request-ID": [...crypto.getRandomValues(new Uint8Array(8))]
      .map((b) => b.toString(16).padStart(2, "0"))
      .join(""),
  };
  if (!(init?.body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
  }
  if (accessToken) headers["Authorization"] = `Bearer ${accessToken}`;
  return fetch(`${BASE}${path}`, { credentials: "include", ...init, headers });
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  let resp = await raw(path, init);
  if (resp.status === 401 && accessToken && refreshHandler) {
    const ok = await refreshHandler();
    if (ok) resp = await raw(path, init);
  }
  // 204/205 (e.g. DELETE /leaves/:id) carry no body even when the server
  // still labels them application/json — parsing would throw and turn a
  // successful call into an error toast.
  const hasBody = resp.status !== 204 && resp.status !== 205 && resp.headers.get("content-length") !== "0";
  const isJson = hasBody && resp.headers.get("content-type")?.includes("application/json");
  const body = isJson ? await resp.json() : null;
  if (!resp.ok) {
    const err = body?.error ?? {};
    throw new ApiError(
      resp.status,
      err.code ?? "error",
      err.message ?? resp.statusText,
      resp.headers.get("x-request-id"),
    );
  }
  return body as T;
}

export function upload<T>(path: string, files: File[]): Promise<T> {
  const form = new FormData();
  for (const f of files) form.append("files", f);
  return api<T>(path, { method: "POST", body: form });
}

export async function blobUrl(path: string): Promise<string> {
  let resp = await raw(path);
  if (resp.status === 401 && accessToken && refreshHandler && (await refreshHandler())) {
    resp = await raw(path);
  }
  if (!resp.ok) throw new ApiError(resp.status, "fetch_failed", "Could not load file");
  return URL.createObjectURL(await resp.blob());
}

export async function download(path: string, filename: string): Promise<void> {
  let resp = await raw(path);
  if (resp.status === 401 && accessToken && refreshHandler && (await refreshHandler())) {
    resp = await raw(path);
  }
  if (!resp.ok) throw new ApiError(resp.status, "download_failed", "Download failed");
  const blob = await resp.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
