import type { Job, Lane } from "../types";

export type NodeStatus = "pending" | "running" | "warning" | "done" | "failed";
export type DataKind = "video" | "audio" | "text";

export const STEP_LABEL: Record<string, string> = {
  preprocess: "Prepare",
  plan: "Plan",
  validate_plan: "Check",
  ground: "Locate",
  separate: "Separate",
  generate: "Generate",
  judge: "Judge",
  score: "Score",
  residual: "Remainder",
  render: "Mix",
};
export const STATUS_LABEL: Record<NodeStatus | "skipped", string> = {
  pending: "Waiting",
  running: "Running",
  warning: "Needs a look",
  done: "Done",
  failed: "Failed",
  skipped: "Skipped",
};
export const DATA_LABEL: Record<DataKind, string> = { video: "Video", audio: "Audio", text: "Text" };

// Trace tool name -> board step.
export const TOOL_STEP: Record<string, string> = {
  plan: "plan",
  validate_plan: "validate_plan",
  separate: "separate",
  judge: "judge",
  locate: "ground",
  mask_video: "ground",
  generate: "generate",
  score_generation: "score",
  preprocess: "preprocess",
  residual: "residual",
  render: "render",
};

// Columns run left to right; each step sits on the lane of the server that runs it.
const COL: Record<string, number> = { preprocess: 0, plan: 1, validate_plan: 2, separate: 3, generate: 3, judge: 4, score: 4, residual: 5, render: 6 };

// Used until /api/system answers: the default deployment's lanes.
export const DEFAULT_LANES: Lane[] = [
  { id: "app", name: "App server", models: [], steps: ["preprocess", "residual", "render"], up: null },
  { id: "planner", name: "Planner", models: [], steps: ["plan"], up: null },
  { id: "validator", name: "Validator", models: [], steps: ["validate_plan"], up: null },
  { id: "separation", name: "Tool server (separation:8700)", models: [], steps: ["separate"], up: null },
  { id: "judge", name: "Tool server (judge:8700)", models: [], steps: ["judge"], up: null },
  { id: "generation", name: "Tool server (generation:8700)", models: [], steps: ["generate", "score"], up: null },
];

type Link = [from: string, to: string, kind: DataKind, loop?: "loop" | null, label?: string];
const LINKS: Link[] = [
  ["preprocess", "plan", "video", null, "Video"], ["preprocess", "validate_plan", "video"], ["preprocess", "generate", "video"],
  ["plan", "validate_plan", "text", null, "Text"], ["validate_plan", "plan", "text", "loop"],
  ["validate_plan", "separate", "text"], ["separate", "judge", "audio", null, "Audio"], ["judge", "separate", "text", "loop"],
  ["judge", "residual", "audio"], ["residual", "render", "audio"],
  ["validate_plan", "generate", "text"], ["generate", "score", "audio", null, "Audio"], ["score", "generate", "text", "loop"],
  ["score", "render", "audio"],
];
const LOOP_TARGETS = new Set(["plan", "separate", "generate"]);

// What crossed an edge: the inputs of the step that received it, or (for a verdict going back) its output.
export const CARRIES: Record<string, { step: string; keys?: string[]; output?: boolean }> = {
  "preprocess>plan": { step: "plan", keys: ["video", "audio", "duration"] },
  "preprocess>validate_plan": { step: "validate_plan", keys: ["video", "audio"] },
  "preprocess>generate": { step: "generate", keys: ["video"] },
  "plan>validate_plan": { step: "validate_plan", keys: ["plans"] },
  "validate_plan>plan": { step: "plan", keys: ["feedback"] },
  "validate_plan>separate": { step: "separate", keys: ["plan"] },
  "validate_plan>generate": { step: "generate", keys: ["plan"] },
  "separate>judge": { step: "judge", keys: ["track"] },
  "judge>separate": { step: "judge", output: true },
  "judge>residual": { step: "residual", keys: ["tracks"] },
  "residual>render": { step: "residual", output: true },
  "generate>score": { step: "score", keys: ["track"] },
  "score>generate": { step: "score", output: true },
  "score>render": { step: "render", keys: ["sources"] },
};

export function edgeInfo(key: string): { from: string; to: string; kind: DataKind; loop: boolean; carry: (typeof CARRIES)[string] } | null {
  const [from, to] = key.replace(/^edge:/, "").split(">");
  const link = LINKS.find((l) => l[0] === from && l[1] === to);
  const carry = CARRIES[`${from}>${to}`];
  return link && carry ? { from, to, kind: link[2], loop: link[3] === "loop", carry } : null;
}

const stepKey = (key: string) => key.split(":")[0];
const PER_SOURCE = ["separate", "judge", "generate", "score"];

export function nodeState(job: Job | null, step: string): { status: NodeStatus; sub: string } {
  const steps = job?.steps.filter((s) => stepKey(s.key) === step) ?? [];
  if (!job || steps.length === 0) return { status: "pending", sub: "" };
  const status = (["failed", "running", "warning", "done"] as const).find((o) => steps.some((s) => s.status === o)) ?? "pending";
  if (step === "plan" || step === "validate_plan") return { status, sub: steps[0].round > 1 ? `Round ${steps[0].round}` : "" };
  if (PER_SOURCE.includes(step)) {
    const origin = step === "separate" || step === "judge" ? "separated" : "generated";
    const total = Math.max(steps.length, job.sources.filter((s) => s.status !== "skipped" && s.origin === origin).length);
    const finished = steps.filter((s) => s.status === "done" || s.status === "warning" || s.status === "failed").length;
    return { status, sub: `${finished}/${total}` };
  }
  return { status, sub: "" };
}

// Short enough for a step box; the lane label keeps the exact IDs.
const PRETTY: Record<string, string> = {
  "gemini-3.8-flash": "Gemini Flash",
  "Qwen3-VL-8B-Instruct": "Qwen3-VL 8B",
  "sam-audio-large-tv": "SAM Audio",
  "sam-audio-judge": "SAM Judge",
  "internal-model": "Internal",
};
const shorten = (text: string, n: number) => (text.length > n ? `${text.slice(0, n - 1)}…` : text);
// With a count on the model line, keep the model clear of it.
export const modelText = (model: string, sub: string) => (sub ? shorten(model, Math.max(4, 15 - sub.length)) : model);
const serverName = (lane: Lane) => lane.name.replace(/^vLLM \(.+\)$/, "vLLM").replace(/ \((.+):\d+\)$/, " $1");

export interface BoardNode { step: string; x: number; y: number; status: NodeStatus; sub: string; idle: boolean; label: string; model: string }
export interface BoardEdge { key: string; from: string; to: string; kind: DataKind; loop: boolean; state: "" | "active" | "done"; d: string }
export interface BoardLabel { text: string; x: number; y: number; loop: boolean; on: boolean }
export interface BoardLane { id: string; name: string; what: string; up: boolean | null; busy: boolean; y: number; h: number; title: string }
export interface Board { width: number; height: number; nodeW: number; nodeH: number; laneH: number; lanes: BoardLane[]; nodes: BoardNode[]; edges: BoardEdge[]; labels: BoardLabel[] }

export function boardLayout(lanesIn: Lane[], job: Job | null): Board {
  const method = job?.method ?? null;
  // Before a start both paths stay possible; after it, the path not taken dims.
  const separating = !job || (!job.silent && method !== "generate");
  const generating =
    !job || !method || method === "generate" || job.silent || job.sources.some((s) => s.origin === "generated") || job.steps.some((s) => stepKey(s.key) === "generate");
  const idle = (step: string) => (["generate", "score"].includes(step) && !generating) || (["separate", "judge", "residual"].includes(step) && !separating);
  const lanes = (lanesIn.length ? lanesIn : DEFAULT_LANES).filter((l) => l.steps.some((s) => s in COL));
  const row = (step: string) => Math.max(0, lanes.findIndex((l) => l.steps.includes(step)));
  const labelW = 150, colW = 124, nodeW = 108, nodeH = 46, laneH = 62, left = labelW + 18, gap = 4, r = 8;
  // A step that shares its column with an earlier step of the same lane (generate with separate, score with judge) takes a second row.
  const order = Object.keys(COL);
  const sub = (step: string) => order.filter((s) => COL[s] === COL[step] && row(s) === row(step) && order.indexOf(s) < order.indexOf(step)).length;
  const laneRows = lanes.map((_, i) => 1 + Math.max(0, ...order.filter((s) => row(s) === i).map(sub)));
  const laneTop = laneRows.map((_, i) => laneRows.slice(0, i).reduce((a, b) => a + b, 0) * laneH);
  const pos = (step: string) => ({ x: left + COL[step] * colW, y: laneTop[row(step)] + sub(step) * laneH + (laneH - nodeH) / 2 });
  const state = Object.fromEntries(Object.keys(COL).map((s) => [s, nodeState(job, s)])) as Record<string, ReturnType<typeof nodeState>>;
  const stepsOf = (step: string) => job?.steps.filter((s) => stepKey(s.key) === step) ?? [];
  // A same-row loop on the bottom lane curves under it; make room for it.
  const lowLoop = LINKS.some(
    ([from, to, , loop]) => loop && row(from) === row(to) && row(to) === lanes.length - 1 && !idle(to) && stepsOf(to).some((s) => (s.round || 1) > 1),
  );
  const width = left + 6 * colW + nodeW + 14;
  const height = laneRows.reduce((a, b) => a + b, 0) * laneH + (lowLoop ? 26 : 0);

  const nodeModel = (step: string) => {
    const lane = lanes.find((l) => l.steps.includes(step));
    if (!lane || lane.id === "app") return "ffmpeg";
    if (step === "score") return "CLAP";
    const id = (lane.models[0] || serverName(lane)).split("/").pop() ?? "";
    return PRETTY[id] || id;
  };

  // Orthogonal routes: forward edges step down then right, or right then up; loops go back the other way.
  const ENTRY: Record<string, number> = { "preprocess>validate_plan": 9, "plan>validate_plan": -9, "preprocess>generate": 9, "validate_plan>generate": -9 };
  const route = (from: string, to: string, loop: boolean) => {
    const a = pos(from), b = pos(to);
    const acx = a.x + nodeW / 2, acy = a.y + nodeH / 2, bcx = b.x + nodeW / 2, bcy = b.y + nodeH / 2;
    if (loop && a.y === b.y) return `M ${acx} ${a.y + nodeH + gap} C ${acx} ${a.y + nodeH + 16}, ${bcx} ${b.y + nodeH + 16}, ${bcx} ${b.y + nodeH + gap}`;
    if (loop) return `M ${acx} ${a.y - gap} L ${acx} ${bcy + r} Q ${acx} ${bcy}, ${acx - r} ${bcy} L ${b.x + nodeW + gap} ${bcy}`;
    if (a.y === b.y) return `M ${a.x + nodeW} ${acy} L ${b.x - gap} ${bcy}`;
    const ey = bcy + (ENTRY[`${from}>${to}`] || 0);
    if (b.y > a.y) return `M ${acx} ${a.y + nodeH} L ${acx} ${ey - r} Q ${acx} ${ey}, ${acx + r} ${ey} L ${b.x - gap} ${ey}`;
    return `M ${a.x + nodeW} ${acy} L ${bcx - r} ${acy} Q ${bcx} ${acy}, ${bcx} ${acy - r} L ${bcx} ${b.y + nodeH + gap}`;
  };

  const edges: BoardEdge[] = [];
  const labels: BoardLabel[] = [];
  const written = new Set<string>();
  const pending: Partial<Record<DataKind, string>> = {};
  for (const [from, to, kind, loopFlag, label] of LINKS) {
    if (idle(from) || idle(to)) continue;
    const loop = loopFlag === "loop";
    const sTo = state[to].status, sFrom = state[from].status;
    // A retry (round 2+) of plan, separate or generate is fed by its loop edge, so only that edge flows;
    // a first run is fed by the forward edges. Loop edges appear once a retry has happened.
    const runs = stepsOf(to).filter((s) => s.status === "running");
    const retrying = runs.some((s) => (s.round || 1) > 1);
    const fresh = runs.some((s) => (s.round || 1) <= 1);
    let edgeState: BoardEdge["state"] = "";
    if (loop) {
      if (!retrying) continue; // drawn only while the retry it causes is running
      edgeState = "active";
    } else if (sFrom !== "pending" && (LOOP_TARGETS.has(to) ? fresh : runs.length > 0)) edgeState = "active";
    else if (sFrom !== "pending" && sTo !== "pending") edgeState = "done";
    edges.push({ key: `edge:${from}>${to}`, from, to, kind, loop, state: edgeState, d: route(from, to, loop) });
    const a = pos(from), b = pos(to);
    if (loop) {
      const below = a.y === b.y;
      labels.push({
        text: "Retry",
        x: below ? (a.x + b.x + nodeW) / 2 : (a.x + nodeW / 2 + b.x + nodeW) / 2,
        y: below ? a.y + nodeH + 26 : b.y + nodeH / 2 - 7,
        loop: true,
        on: edgeState === "active",
      });
    } else if ((label || pending[kind]) && !written.has((label || pending[kind]) as string)) {
      // Name the data where its type changes, above a horizontal stretch of the edge;
      // a gap too narrow for the word hands it to the next edge of the same type.
      const text = (label || pending[kind]) as string;
      const acy = a.y + nodeH / 2, ey = b.y + nodeH / 2 + (ENTRY[`${from}>${to}`] || 0);
      let at: [number, number] | null = null;
      if (b.y > a.y) at = [(a.x + nodeW / 2 + b.x) / 2, ey - 7];
      else if (b.y < a.y) at = [(a.x + nodeW + b.x + nodeW / 2) / 2, acy - 7];
      else if (b.x - a.x - nodeW >= 60) at = [(a.x + nodeW + b.x) / 2, acy - 7];
      if (at) {
        written.add(text);
        delete pending[kind];
        labels.push({ text, x: at[0], y: at[1], loop: false, on: false });
      } else pending[kind] = text;
    }
  }

  return {
    width,
    height,
    nodeW,
    nodeH,
    laneH,
    lanes: lanes.map((lane, i) => ({
      id: lane.id,
      name: shorten(serverName(lane), 19),
      what: shorten(lane.up === false ? "Not responding" : lane.id === "app" ? "ffmpeg" : (lane.models[0] || "").split("/").pop() ?? "", 22),
      up: lane.up,
      busy: lane.steps.some((s) => state[s]?.status === "running"),
      y: laneTop[i],
      h: laneRows[i] * laneH,
      title: `${serverName(lane)}: ${lane.models.join(", ") || "ffmpeg"}`,
    })),
    // Idle nodes first: with every step on one server, the live node is drawn over the dimmed one.
    nodes: Object.keys(COL)
      .map((step) => ({
        step,
        ...pos(step),
        ...state[step],
        idle: idle(step),
        label: STEP_LABEL[step],
        model: shorten(nodeModel(step), 13),
      }))
      .sort((a, b) => Number(b.idle) - Number(a.idle)),
    edges,
    labels,
  };
}
