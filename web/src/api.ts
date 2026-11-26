import type { Command, Job, Lane, Method, RouteResult, TraceCall } from "./types";

export class ApiError extends Error {
  constructor(public status: number, public detail: string) {
    super(detail);
  }
}

// FastAPI sends {"detail": "text"} or {"detail": [{"msg": ...}]} for validation errors.
async function detailOf(response: Response): Promise<string> {
  const text = await response.text();
  try {
    const detail = JSON.parse(text)?.detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) return detail.map((d) => d?.msg ?? String(d)).join(" ");
  } catch {
    // Not JSON: use the text as is.
  }
  return text || response.statusText;
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  if (!response.ok) throw new ApiError(response.status, await detailOf(response));
  return (await response.json()) as T;
}

const post = <T>(url: string, body: unknown) =>
  request<T>(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

export const listJobs = () => request<Job[]>("/api/jobs");
export const getJob = (id: string) => request<Job>(`/api/jobs/${id}`);
export const uploadVideo = (file: File | Blob) => {
  const form = new FormData();
  form.append("file", file);
  return request<Job>("/api/jobs", { method: "POST", body: form });
};
export const startJob = (id: string, method: Method) => post<Job>(`/api/jobs/${id}/start`, { method });
export const sendCommand = (id: string, cmd: Command) => post<Job>(`/api/jobs/${id}/commands`, cmd);
export const getTrace = (id: string) => request<TraceCall[]>(`/api/jobs/${id}/trace`);
export const getSystem = () => request<Lane[]>("/api/system");
export const routeRequest = (id: string, text: string) => post<RouteResult>(`/api/jobs/${id}/route`, { request: text });
export const exportUrl = (id: string) => `/api/jobs/${id}/export`;
export const fileUrl = (id: string, path: string) =>
  `/api/jobs/${id}/files/${path.split("/").map(encodeURIComponent).join("/")}`;
export const jobEvents = (id: string) => new EventSource(`/api/jobs/${id}/events`);
