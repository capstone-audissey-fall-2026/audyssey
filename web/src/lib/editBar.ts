import type { JobView } from "./adapter";
import { pitchCommands } from "./trackActions";
import type { Command } from "../types";

export const RESIDUAL_NAME = "Rest of the original audio";

export interface Target { id: string; name: string; gain: number; pitch: number | null }

// Everything a request can point at: the tracks, plus the residual when there is one.
export function targets(view: JobView): Target[] {
  const list: Target[] = view.rows.map((r) => ({ id: r.id, name: r.name, gain: r.gain, pitch: r.pitch }));
  if (view.residual) list.push({ id: "residual", name: RESIDUAL_NAME, gain: view.residual.gain, pitch: null });
  return list;
}

const percent = (gain: number) => `${Math.round(gain * 100)}%`;
const semitones = (v: number) => `${v > 0 ? "+" : ""}${v} st`;

// What will change, with the current value, so the card can be checked before it runs.
export function commandSentence(command: Command, view: JobView): string {
  if (command.type === "render") return "Mix the result";
  if (command.type === "add_source") return `Add source: ${command.plan.name} (${command.method})`;
  const target = targets(view).find((t) => t.id === command.source_id);
  const name = target?.name ?? command.source_id;
  switch (command.type) {
    case "set_gain":
      return `${name} volume ${target ? percent(target.gain) : "?"} → ${percent(command.gain)}`;
    case "set_pitch":
      return `${name} pitch ${semitones(target?.pitch ?? 0)} → ${semitones(command.semitones)}`;
    case "drop":
      return `Turn off ${name}`;
    case "keep":
      return `Turn on ${name}`;
    case "reseparate":
      return `Re-separate ${name}`;
    case "generate":
      return `Generate ${name} instead`;
  }
}

// A pitch change is heard only after a render.
export function commandsFor(command: Command): Command[] {
  return command.type === "set_pitch" ? pitchCommands(command.source_id, command.semitones) : [command];
}
