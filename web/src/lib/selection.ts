// The first two follow the approved mockup (--c-player, --c-enemy); the rest are vivid and distinct on video.
const OBJECT_COLORS = ["#4cc9f0", "#ff7ab6", "#ffd166", "#9be564", "#ff8c42", "#b388ff", "#ff4d4d", "#2ec4b6"];
export const NONE_COLOR = "#9aa3b2";

// Rows cycle through the palette (never gray); a negative index means "no colour".
export function objectColor(index: number): string {
  return index < 0 ? NONE_COLOR : OBJECT_COLORS[index % OBJECT_COLORS.length];
}
