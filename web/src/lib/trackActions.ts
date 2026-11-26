import type { Command } from "../types";
import type { JobView } from "./adapter";

// The keep switch. Within a separated/generated pair only one plays, so turning one on turns the other off.
export function keepCommands(view: JobView, id: string, keep: boolean): Command[] {
  const commands: Command[] = [{ type: keep ? "keep" : "drop", source_id: id }];
  if (!keep || id === "residual") return commands;
  const row = view.rows.find((r) => r.id === id);
  const other = row?.pairOf ? view.rows.find((r) => r.id === row.pairOf) : undefined;
  if (other?.keep) commands.push({ type: "drop", source_id: other.id });
  return commands;
}
