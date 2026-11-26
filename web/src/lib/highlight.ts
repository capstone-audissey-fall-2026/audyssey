import type { Source } from "../types";
import type { TrackRow } from "./adapter";

// A visual hint is one box at one moment; it is drawn a little before and after.
const WINDOW = 0.5;

export interface HighlightBox { id: string; box: [number, number, number, number]; color: string }

// The selected source's box, or every source's box when nothing is selected.
export function visibleBoxes(rows: TrackRow[], sources: Source[], selected: string | null, t: number): HighlightBox[] {
  const boxes: HighlightBox[] = [];
  for (const row of rows) {
    const hint = sources.find((s) => s.id === row.id)?.plan.visual_hint;
    if (!hint || (selected !== null && selected !== row.id)) continue;
    if (Math.abs(t - hint.time) <= WINDOW) boxes.push({ id: row.id, box: hint.box, color: row.color });
  }
  return boxes;
}

export function highlightChip(row: Pick<TrackRow, "name">, source: Source): string {
  return source.plan.visual_hint ? `Highlighting ${row.name}` : `${row.name} has no on-screen location`;
}

// Where a video of vw x vh sits inside a box of boxW x boxH (object-fit: contain), as fractions of the box.
export function contentRect(boxW: number, boxH: number, vw: number, vh: number): { x: number; y: number; w: number; h: number } {
  if (!vw || !vh || !boxW || !boxH) return { x: 0, y: 0, w: 1, h: 1 };
  const scale = Math.min(boxW / vw, boxH / vh);
  const w = (vw * scale) / boxW;
  const h = (vh * scale) / boxH;
  return { x: (1 - w) / 2, y: (1 - h) / 2, w, h };
}
