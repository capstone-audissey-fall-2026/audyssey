import type { Span } from "../types";

// Span edits that have not been sent yet, one draft per source. "Regenerate with new spans" sends them.
export class PendingEdits {
  private drafts = new Map<string, Span[]>();

  get(sourceId: string): Span[] | null {
    return this.drafts.get(sourceId) ?? null;
  }

  set(sourceId: string, spans: Span[]): void {
    this.drafts.set(sourceId, spans);
  }

  // One source, or all of them.
  discard(sourceId?: string): void {
    if (sourceId === undefined) this.drafts.clear();
    else this.drafts.delete(sourceId);
  }

  dirty(): string[] {
    return [...this.drafts.keys()];
  }
}
