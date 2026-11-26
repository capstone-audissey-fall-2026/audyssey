import { useSyncExternalStore } from "react";
import { ApiError, getJob, jobEvents } from "../api";
import type { Job } from "../types";
import { errorDetail } from "./errors";

export function errorText(error: unknown): string {
  if (error instanceof ApiError && error.status === 409) return "Another change is still running.";
  if (error instanceof TypeError) return "Could not reach the server. Check that it is running, then try again.";
  return errorDetail(error);
}

interface Snapshot { job: Job | null; busy: string | null; error: string | null }

// Follows one job over SSE and runs one change at a time. Messages from another job, or older than what
// the view already has, are dropped.
export class JobController {
  job: Job | null = null;
  busy: string | null = null;
  error: string | null = null;
  snapshot: Snapshot = { job: null, busy: null, error: null };
  private id: string | null = null;
  private events: EventSource | null = null;
  private listeners = new Set<() => void>();

  private emit(): void {
    this.snapshot = { job: this.job, busy: this.busy, error: this.error };
    for (const l of this.listeners) l();
  }

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  getSnapshot = (): Snapshot => this.snapshot;

  receive = (incoming: Job): void => {
    if (incoming.id !== this.id) return;
    if (this.job && incoming.version < this.job.version) return;
    this.job = incoming;
    this.emit();
  };

  follow = async (id: string | null): Promise<void> => {
    this.events?.close();
    this.events = null;
    this.id = id;
    this.job = null;
    this.busy = null;
    this.error = null;
    this.emit();
    if (!id) return;
    const stream = jobEvents(id);
    stream.onmessage = (message) => {
      try {
        this.receive(JSON.parse(message.data) as Job);
      } catch {
        // A malformed message is ignored; the next one replaces it.
      }
    };
    this.events = stream;
    try {
      this.receive(await getJob(id));
    } catch (error) {
      if (this.id !== id) return;
      this.error = errorText(error);
      this.emit();
    }
  };

  run = async <T>(label: string, fn: () => Promise<T>): Promise<T | undefined> => {
    if (this.busy !== null) return undefined;
    const id = this.id;
    this.busy = label;
    this.error = null;
    this.emit();
    try {
      return await fn();
    } catch (error) {
      if (this.id === id) this.error = errorText(error);
      return undefined;
    } finally {
      if (this.id === id) {
        this.busy = null;
        this.emit();
      }
    }
  };

  dispose(): void {
    this.events?.close();
    this.events = null;
    this.listeners.clear();
  }
}

const controller = new JobController();

export function useJob() {
  const { job, busy, error } = useSyncExternalStore(controller.subscribe, controller.getSnapshot, controller.getSnapshot);
  return { job, busy, error, follow: controller.follow, run: controller.run, receive: controller.receive };
}
