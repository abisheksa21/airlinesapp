export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  const text = await response.text();
  let body: unknown = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = null;
  }
  if (!response.ok) {
    const detail = typeof body === "object" && body !== null && "detail" in body
      ? String((body as { detail?: unknown }).detail ?? response.statusText)
      : response.statusText;
    throw new ApiError(response.status, detail || "Request failed (" + response.status + ")");
  }
  return body as T;
}
