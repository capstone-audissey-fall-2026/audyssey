import { useEffect, useRef, type ReactNode } from "react";
import { fileUrl } from "../api";
import { DATA_LABEL, STEP_LABEL, TOOL_STEP, edgeInfo, nodeState } from "../lib/board";
import type { Job, Lane, TraceCall } from "../types";
import Icon from "./Icon";

type Obj = Record<string, unknown>;
const isObj = (v: unknown): v is Obj => typeof v === "object" && v !== null && !Array.isArray(v);
const isPlan = (v: unknown): v is Obj => isObj(v) && "description" in v && "kind" in v && "name" in v;
const seconds = (n: number) => `${n.toFixed(1)} s`;

// A step's calls, newest first.
export const callsOf = (calls: TraceCall[], step: string) => calls.filter((c) => TOOL_STEP[c.tool] === step).reverse();

function Plans({ plans }: { plans: Obj[] }) {
  return (
    <div className="plans">
      {plans.map((p, i) => (
        <div className="plan" key={i}>
          <b>{String(p.name)}</b> <span className="k">{String(p.kind)}</span>
          <div>{String(p.description)}</div>
          {Array.isArray(p.spans) && p.spans.length ? (
            <div className="spans">{(p.spans as { start: number; end: number }[]).map((s) => `${s.start.toFixed(2)}–${s.end.toFixed(2)} s`).join(", ")}</div>
          ) : null}
        </div>
      ))}
    </div>
  );
}

function FileView({ path, jobId }: { path: string; jobId: string }) {
  const ext = path.split(".").pop()?.toLowerCase() ?? "";
  const name = path.split("/").pop() ?? path;
  const src = fileUrl(jobId, path);
  if (["jpg", "jpeg", "png"].includes(ext)) return <img alt={name} className="trace-img" src={src} />;
  if (["mp4", "mov", "webm", "mkv"].includes(ext)) return <figure className="trace-fig"><video controls playsInline preload="metadata" src={src} /><figcaption>{name}</figcaption></figure>;
  if (["wav", "mp3", "flac"].includes(ext)) return <div><div className="cap">{name}</div><audio controls preload="none" src={src} /></div>;
  return <a href={src}>{name}</a>;
}

function Value({ v, jobId }: { v: unknown; jobId: string }): ReactNode {
  if (isObj(v) && typeof v.file === "string") return <FileView jobId={jobId} path={v.file} />;
  if (Array.isArray(v)) {
    if (v.length && v.every(isPlan)) return <Plans plans={v as Obj[]} />;
    return v.length ? <div className="plans">{v.map((x, i) => <Value jobId={jobId} key={i} v={x} />)}</div> : <span className="cap">—</span>;
  }
  if (isObj(v)) {
    if (isPlan(v)) return <Plans plans={[v]} />;
    return (
      <dl className="kv">
        {Object.entries(v).flatMap(([k, x]) => [<dt key={`${k}-t`}>{k}</dt>, <dd key={`${k}-d`}><Value jobId={jobId} v={x} /></dd>])}
      </dl>
    );
  }
  if (typeof v === "number") return String(Math.round(v * 1000) / 1000);
  return String(v ?? "");
}

function Output({ call, jobId }: { call: TraceCall; jobId: string }) {
  const o = call.output;
  if (call.tool === "plan" && Array.isArray(o)) return <Plans plans={o as Obj[]} />;
  if (call.tool === "validate_plan" && Array.isArray(o)) {
    if (o.length === 0) return <span className="verdict yes">No issues</span>;
    return (
      <div className="plans">
        {(o as { source_name: string | null; message: string }[]).map((i, n) => (
          <div className="plan issue" key={n}><b>{i.source_name || "Whole plan"}</b><div>{i.message}</div></div>
        ))}
      </div>
    );
  }
  if ((call.tool === "judge" || call.tool === "score_generation") && isObj(o)) {
    const scores = (o.scores ?? {}) as Record<string, number>;
    return (
      <div>
        <span className={`verdict ${o.passed ? "yes" : "no"}`}>{o.passed ? "Passed" : "Try again"}</span>
        <dl className="kv">{Object.entries(scores).flatMap(([k, v]) => [<dt key={`${k}-t`}>{k}</dt>, <dd key={`${k}-d`}>{Number(v).toFixed(3)}</dd>])}</dl>
        {o.reason ? <div className="cap">{String(o.reason)}</div> : null}
      </div>
    );
  }
  return <Value jobId={jobId} v={o} />;
}

const pretty = (raw: unknown) => {
  if (raw == null) return "—";
  try {
    return JSON.stringify(JSON.parse(String(raw)), null, 2);
  } catch {
    return String(raw);
  }
};

interface Media { kind: string; file: string; label: string }

function Request({ r, jobId }: { r: Obj; jobId: string }) {
  const media = (r.media ?? []) as Media[];
  const frames = media.filter((m) => m.kind === "image");
  const clips = media.filter((m) => m.kind === "video");
  const audios = media.filter((m) => m.kind === "audio");
  const how = r.input === "audio" ? "audio check" : r.input === "video" ? `video ${r.fps} fps${r.audio ? " + audio" : ""}` : `frames ${r.fps} fps`;
  const attempt = Number(r.attempt ?? 1);
  const usage = r.usage as { input_tokens: number; output_tokens: number; total_tokens: number } | undefined;
  return (
    <>
      <div className="block">
        <div className="block-head">
          <span className="tag in">Input</span>
          <span>{`${String(r.model).split("/").pop()}, ${how}${attempt > 1 ? `, retry ${attempt}` : ""}`}</span>
        </div>
        {frames.length ? (
          <div className="frames">
            {frames.map((m) => (
              <figure key={m.file}>
                <img alt={m.label} loading="lazy" src={fileUrl(jobId, m.file)} />
                <figcaption>{m.label.replace(/^Frame at (.+) seconds$/, "$1 s")}</figcaption>
              </figure>
            ))}
          </div>
        ) : null}
        {clips.length ? (
          <div className="clips">
            {clips.map((m) => (
              <figure key={m.file}>
                <video controls playsInline preload="metadata" src={fileUrl(jobId, m.file)} />
                <figcaption>{m.label.replace(/^Video from (.+) to (.+) seconds$/, "$1–$2 s")}</figcaption>
              </figure>
            ))}
          </div>
        ) : null}
        {audios.length ? (
          <div className="clips">
            {audios.map((m) => (
              <figure key={m.file}>
                <audio controls preload="metadata" src={fileUrl(jobId, m.file)} />
                <figcaption>{m.label}</figcaption>
              </figure>
            ))}
          </div>
        ) : null}
        <pre>{String(r.text ?? "")}</pre>
        <details className="sub">
          <summary>Prompt</summary>
          <pre>{String(r.system ?? "")}</pre>
        </details>
      </div>
      <div className="block">
        <div className="block-head">
          <span className="tag out">Response</span>
          {usage?.total_tokens ? <span>{`${usage.input_tokens} + ${usage.output_tokens} tokens`}</span> : null}
        </div>
        <pre>{pretty(r.raw)}</pre>
      </div>
    </>
  );
}

function callTitle(c: TraceCall, job: Job): string {
  const id = c.step.includes(":") ? c.step.split(":")[1] : null;
  const plan = c.inputs?.plan as { name?: string } | undefined;
  return (id && job.sources.find((s) => s.id === id)?.plan.name) || plan?.name || STEP_LABEL[TOOL_STEP[c.tool]] || c.tool;
}

function Call({ call, job, open }: { call: TraceCall; job: Job; open: boolean }) {
  const inputs = Object.fromEntries(Object.entries(call.inputs ?? {}).filter(([k, v]) => k !== "out" && v !== null));
  return (
    <details className="call" data-id={call.id} open={open}>
      <summary>
        <Icon name="info" />
        {callTitle(call, job)}
        <span className="meta">{seconds(call.seconds)}</span>
      </summary>
      {call.error ? (
        <div className="block">
          <div className="block-head"><span className="tag err">Error</span></div>
          <pre>{call.error}</pre>
        </div>
      ) : null}
      {call.requests?.length ? (
        call.requests.map((r, i) => <Request jobId={job.id} key={i} r={r} />)
      ) : (
        <div className="block">
          <div className="block-head"><span className="tag in">Input</span></div>
          <Value jobId={job.id} v={inputs} />
        </div>
      )}
      {call.output !== null && call.output !== undefined ? (
        <div className="block">
          <div className="block-head"><span className="tag out">Output</span></div>
          <Output call={call} jobId={job.id} />
        </div>
      ) : null}
    </details>
  );
}

interface InspectorProps {
  open: boolean;
  onClose: () => void;
  step: string | null;
  job: Job;
  lane: Lane | undefined;
  calls: TraceCall[]; // the whole trace
}

// The calls of one pipeline step: inputs, prompts, frames and clips, responses, scores, errors.
export default function Inspector({ open, onClose, step, job, lane, calls }: InspectorProps) {
  const ref = useRef<HTMLDialogElement | null>(null);
  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);
  const mine = step ? callsOf(calls, step) : [];
  const running = step ? nodeState(job, step).status === "running" : false;
  return (
    <dialog
      aria-labelledby="drawer-title"
      className="drawer"
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
      onClose={onClose}
      ref={ref}
    >
      <div className="drawer-head">
        <div>
          <h2 id="drawer-title">{step ? STEP_LABEL[step] : ""}</h2>
          <div className="where">{lane ? [lane.name, ...lane.models].join("  /  ") : ""}</div>
        </div>
        <button aria-label="Close" className="btn sm ico" onClick={onClose} type="button">×</button>
      </div>
      <div className="drawer-body">
        {mine.length === 0 ? (
          <p className="none">{running ? "Running…" : "No calls recorded"}</p>
        ) : (
          mine.map((call, i) => <Call call={call} job={job} key={call.id} open={i === 0} />)
        )}
      </div>
    </dialog>
  );
}

interface EdgePopoverProps {
  edge: string;
  job: Job;
  calls: TraceCall[];
  x: number; // where the edge was clicked
  y: number;
  onClose: () => void;
}

// Shows only what crossed one edge, per call of the step that received it.
export function EdgePopover({ edge, job, calls, x, y, onClose }: EdgePopoverProps) {
  const info = edgeInfo(edge);
  const ref = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    ref.current?.querySelector<HTMLElement>("button")?.focus();
  }, [edge]);
  if (!info) return null;
  const { from, to, kind, loop, carry } = info;
  const mine = callsOf(calls, carry.step);
  return (
    <div
      aria-label={`${STEP_LABEL[from]} to ${STEP_LABEL[to]}`}
      className="edgepop"
      ref={ref}
      role="dialog"
      style={{ left: `clamp(8px, ${x - 200}px, calc(100vw - 408px))`, top: `${y + 12}px` }}
    >
      <div className="edgepop-head">
        <span className="kind" style={{ background: `var(--${kind})` }} />
        <div>
          <h2>{`${STEP_LABEL[from]} → ${STEP_LABEL[to]}`}</h2>
          <div className="where">{loop ? `${DATA_LABEL[kind]}, verdict sent back to retry` : `${DATA_LABEL[kind]}, input received by ${STEP_LABEL[to]}`}</div>
        </div>
        <button aria-label="Close" className="btn sm ico" onClick={onClose} type="button">×</button>
      </div>
      <div className="edgepop-body">
        {mine.length === 0 ? (
          <p className="none">Nothing sent yet</p>
        ) : (
          mine.map((call, i) => {
            const shown = carry.output ? (
              <Output call={call} jobId={job.id} />
            ) : (
              (() => {
                const keys = (carry.keys ?? []).filter((k) => call.inputs?.[k] != null);
                const value = Object.fromEntries(keys.map((k) => [k, call.inputs[k]]));
                return <Value jobId={job.id} v={carry.keys?.length === 1 ? value[carry.keys[0]] : value} />;
              })()
            );
            return (
              <details className="call" data-id={call.id} key={call.id} open={i === 0}>
                <summary>
                  {callTitle(call, job)}
                  <span className="meta">{seconds(call.seconds)}</span>
                </summary>
                <div className="block">
                  <div className="block-head"><span className={`tag ${loop ? "out" : "in"}`}>{loop ? "Verdict" : "Sent"}</span></div>
                  {shown}
                </div>
              </details>
            );
          })
        )}
      </div>
    </div>
  );
}
