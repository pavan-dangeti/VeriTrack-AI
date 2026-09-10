const BASE = "/api/v1";

let accessToken: string | null = null;
let refreshHandler: (() => Promise<boolean>) | null = null;

export function setAccessToken(token: string | null) {
  accessToken = token;
}

export function getAccessToken() {
  return accessToken;
}

export function setRefreshHandler(fn: () => Promise<boolean>) {
  refreshHandler = fn;
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
    // Correlation id: the backend echoes it into logs + error bodies.
    "X-Request-ID": [...crypto.getRandomValues(new Uint8Array(8))]
      .map((b) => b.toString(16).padStart(2, "0"))
      .join(""),
  };
  if (!(init?.body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
  }
  if (accessToken) headers["Authorization"] = `Bearer ${accessToken}`;
  return fetch(`${BASE}${path}`, { ...init, headers });
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  let resp = await raw(path, init);
  if (resp.status === 401 && accessToken && refreshHandler) {
    const ok = await refreshHandler();
    if (ok) resp = await raw(path, init);
  }
  const isJson = resp.headers.get("content-type")?.includes("application/json");
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

/** Blob download with auth header (report PDFs / Excel / exports). */
export async function download(path: string, filename: string): Promise<void> {
  const resp = await raw(path);
  if (!resp.ok) throw new ApiError(resp.status, "download_failed", "Download failed");
  const blob = await resp.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
