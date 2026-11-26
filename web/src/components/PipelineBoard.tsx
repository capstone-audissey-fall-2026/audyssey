import { useState, type KeyboardEvent, type MouseEvent } from "react";
import { DATA_LABEL, STATUS_LABEL, STEP_LABEL, boardLayout, modelText, stepStrip } from "../lib/board";
import Icon from "./Icon";
import type { Job, Lane } from "../types";

interface PipelineBoardProps {
  job: Job | null;
  lanes: Lane[];
  step: string | null; // the step whose inspector is open
  edge: string | null; // the edge whose popover is open
  onStep: (step: string) => void;
  onEdge: (key: string, x: number, y: number) => void;
}

const GLYPH: Record<string, string> = { done: "M-3 0l2 2 4-4", warning: "M0 -3.5v3.5M0 3h0", failed: "M-2.5 -2.5l5 5M2.5 -2.5l-5 5" };

// Collapsible: open while the job runs, closed when it is ready; the person's own toggle wins.
export default function PipelineBoard({ job, lanes, step: openStep, edge: openEdge, onStep, onEdge }: PipelineBoardProps) {
  const [userOpen, setUserOpen] = useState<boolean | null>(null);
  const open = userOpen ?? job?.state === "running";
  const board = boardLayout(lanes, job);
  const known = lanes.filter((l) => l.up !== null);

  const edgeKeys = (event: KeyboardEvent<SVGPathElement>, key: string) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault();
    // From the keyboard, anchor at the middle of the edge.
    const path = event.currentTarget;
    const point = path.getPointAtLength(path.getTotalLength() / 2);
    const m = path.getScreenCTM();
    if (m) onEdge(key, point.x * m.a + m.e, point.y * m.d + m.f);
  };

  return (
    <section className="board-panel panel" aria-label="Pipeline">
      <h2 className="board-head">
        <button aria-controls="board" aria-expanded={open} className="board-toggle" onClick={() => setUserOpen(!open)} type="button">
          <span aria-hidden="true">{open ? "▾" : "▸"}</span>
          Pipeline
        </button>
        {open ? null : (
          <ol className="step-strip">
            {stepStrip(board).map((s) => (
              <li key={s.step}>
                <button
                  aria-label={`${s.label}: ${STATUS_LABEL[s.status]}${s.sub ? `, ${s.sub}` : ""}`}
                  className={`step-chip ${s.status}`}
                  onClick={() => {
                    setUserOpen(true);
                    onStep(s.step);
                  }}
                  type="button"
                >
                  {s.label}
                  {s.status === "done" ? <span aria-hidden="true" className="mk">✓</span> : null}
                  {s.status === "running" ? <Icon name="spin" /> : null}
                  {s.status === "warning" || s.status === "failed" ? <span aria-hidden="true" className="mk">!</span> : null}
                  {s.sub ? <span className="sub">{s.sub}</span> : null}
                </button>
              </li>
            ))}
          </ol>
        )}
        <span className="board-meta">{known.length ? `Servers ${known.filter((l) => l.up).length}/${known.length} up` : ""}</span>
      </h2>
      {open ? (
        <svg className="flow" id="board" viewBox={`0 0 ${board.width} ${board.height}`} role="group" aria-label="Pipeline steps">
          <defs>
            {(["video", "audio", "text"] as const).map((kind) => (
              <marker id={`tip-${kind}`} key={kind} markerHeight="7" markerWidth="7" orient="auto-start-reverse" refX="7" refY="4" viewBox="0 0 8 8">
                <path className={`tip ${kind}`} d="M1 1L7 4L1 7z" />
              </marker>
            ))}
          </defs>
          {board.lanes.map((lane) => (
            <g className={`blane${lane.busy ? " busy" : ""}`} key={lane.id}>
              <rect className="band" height={lane.h - 4} rx="10" width={board.width} x="0" y={lane.y + 2} />
              <circle className={`ldot ${lane.up === true ? "ok" : lane.up === false ? "bad" : "unknown"}`} cx="14" cy={lane.y + lane.h / 2 - 7} r="3.5" />
              <text className="lname" x="24" y={lane.y + lane.h / 2 - 3}>{lane.name}</text>
              <text className={`lmodel${lane.up === false ? " down" : ""}`} x="24" y={lane.y + lane.h / 2 + 13}>{lane.what}</text>
              <title>{lane.title}</title>
            </g>
          ))}
          {board.edges.map((edge) => (
            <g className={`link${openEdge === edge.key ? " selected" : ""}`} key={edge.key}>
              <path className={`edge ${edge.kind} ${edge.state}`} d={edge.d} markerEnd={`url(#tip-${edge.kind})`} />
              {edge.state === "active" ? <path className={`pulse ${edge.kind}`} d={edge.d} /> : null}
              <path
                aria-expanded={openEdge === edge.key}
                aria-haspopup="dialog"
                aria-label={`Show the ${DATA_LABEL[edge.kind].toLowerCase()} sent from ${STEP_LABEL[edge.from]} to ${STEP_LABEL[edge.to]}`}
                className="hit"
                d={edge.d}
                onClick={(event: MouseEvent<SVGPathElement>) => onEdge(edge.key, event.clientX, event.clientY)}
                onKeyDown={(event) => edgeKeys(event, edge.key)}
                role="button"
                tabIndex={0}
              />
            </g>
          ))}
          {board.labels.map((label, i) => (
            <text className={`elabel${label.loop ? " loop" : ""}${label.on ? " on" : ""}`} key={i} textAnchor="middle" x={label.x} y={label.y}>
              {label.text}
            </text>
          ))}
          {board.nodes.map((node) => {
            const count = node.sub ? `, ${node.sub}` : "";
            return (
              <g
                className={`node ${node.status}${node.idle ? " idle" : ""}${openStep === node.step ? " selected" : ""}`}
                key={node.step}
                onClick={() => onStep(node.step)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    onStep(node.step);
                  }
                }}
                role="button"
                tabIndex={0}
                aria-label={`${node.label}, ${node.model}, ${STATUS_LABEL[node.status]}${count}`}
              >
                <rect className="box" height={board.nodeH} rx="10" width={board.nodeW} x={node.x} y={node.y} />
                <text className="label" x={node.x + 11} y={node.y + 19}>{node.label}</text>
                <text className="model" x={node.x + 11} y={node.y + 35}>{modelText(node.model)}</text>
                {node.status !== "pending" ? (
                  <g className={`badge ${node.status}`} transform={`translate(${node.x + board.nodeW - 14} ${node.y + 15})`}>
                    <circle r="7" />
                    {GLYPH[node.status] ? <path d={GLYPH[node.status]} /> : null}
                  </g>
                ) : null}
                {node.sub ? (
                  <text className="count" x={node.x + 11} y={node.y + 51}>{node.sub}</text>
                ) : null}
              </g>
            );
          })}
        </svg>
      ) : null}
    </section>
  );
}
