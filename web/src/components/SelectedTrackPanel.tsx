import { useId, useState } from "react";
import type { TrackRow } from "../lib/adapter";
import { trackFailureText } from "../lib/errors";
import { METHOD_LABEL } from "../lib/newTrack";
import { statusView } from "../lib/selection";
import { pitchCommands, primaryAction } from "../lib/trackActions";
import type { Command, Job, Method, Span } from "../types";
import Icon, { STATUS_ICON } from "./Icon";

interface SelectedTrackPanelProps {
  row: TrackRow;
  job: Job;
  pendingSpans: Span[] | null; // unsent span edits of this track
  disabled: string | null; // why changes are unavailable right now
  error: string | null;
  hasUnsavedEdits: boolean;
  onDiscardEdits: () => void;
  onAction: (label: string, commands: Command[]) => void;
  initialMethod?: Method;
}

const STATUS_CLASS = { ok: "done", run: "run", wait: "queue", err: "fail" } as const;

export default function SelectedTrackPanel({ row, job, pendingSpans, disabled, error, hasUnsavedEdits, onDiscardEdits, onAction, initialMethod }: SelectedTrackPanelProps) {
  const uid = useId();
  const [method, setMethod] = useState<Method>(initialMethod ?? (row.origin === "generated" ? "generate" : "separate"));
  const [edited, setEdited] = useState<string | null>(null);
  const description = edited ?? row.description;
  const status = statusView(row, job.state === "running");
  const action = primaryAction(row, method, pendingSpans, job, description);
  const whyId = `${uid}-why`;
  const reason = disabled ?? ("disabledReason" in action ? action.disabledReason : null);
  const hasAudio = row.status === "done" && row.trackPath !== null;
  const pitchLabel = `${row.pitch > 0 ? "+" : ""}${row.pitch} st`;

  return (
    <section className="side-group" aria-label="Selected track">
      <h2>Selected track</h2>
      <article className="detail sel" style={{ ["--oc" as string]: row.color }} aria-label={row.name}>
        <div className="d-head">
          <span className="sw" style={{ background: row.color }} aria-hidden="true" />
          <h3>{row.name}</h3>
          {status.label ? (
            <span className={`st st-${STATUS_CLASS[status.tone ?? "err"]}`}>
              <Icon name={STATUS_ICON[status.tone ?? "err"]} />
              {status.label}
            </span>
          ) : null}
        </div>
        <div className="d-meta">
          <span className={`badge ${row.origin === "separated" ? "badge-sep" : "badge-gen"}`}>{row.origin === "separated" ? "Separated" : "Generated"}</span>
          <span>{row.kind}</span>
          {row.attempts > 0 ? <span>Attempt {row.attempts}</span> : null}
        </div>
        {row.status === "failed" ? (
          <div className="err">
            <Icon name="x" />
            <div>{trackFailureText(row.failure)}</div>
          </div>
        ) : null}
        {row.filter ? (
          <div className="judge">
            <p>Quality check: {row.filter.passed ? "passed" : "did not pass"}</p>
            {row.filter.reason ? <p className="hint">{row.filter.reason}</p> : null}
            {Object.keys(row.filter.scores).length > 0 ? (
              <p className="hint">
                {Object.entries(row.filter.scores)
                  .map(([name, score]) => `${name} ${score.toFixed(2)}`)
                  .join(" · ")}
              </p>
            ) : null}
          </div>
        ) : null}
        <div className="desc">
          <label htmlFor={`${uid}-method`}>Method</label>
          <select id={`${uid}-method`} value={method} onChange={(e) => setMethod(e.target.value as Method)}>
            <option value="separate">{METHOD_LABEL.separate}</option>
            <option value="generate">{METHOD_LABEL.generate}</option>
          </select>
        </div>
        <div className="desc">
          <label htmlFor={`${uid}-desc`}>Description</label>
          <textarea id={`${uid}-desc`} rows={2} value={description} onChange={(e) => setEdited(e.target.value)} />
        </div>
        <div className="actions">
          <button
            type="button"
            className="btn sm"
            disabled={disabled !== null || "disabledReason" in action}
            aria-describedby={reason ? whyId : undefined}
            onClick={() => "command" in action && onAction(action.label, [action.command])}
          >
            {action.label}
          </button>
          {hasAudio ? (
            <span className="stepper" role="group" aria-label="Pitch">
              <button
                aria-label="Lower pitch"
                className="btn sm ico"
                disabled={disabled !== null || row.pitch <= -12}
                onClick={() => onAction("Changing pitch", pitchCommands(row.id, row.pitch - 1))}
                type="button"
              >
                −
              </button>
              <output>{pitchLabel}</output>
              <button
                aria-label="Raise pitch"
                className="btn sm ico"
                disabled={disabled !== null || row.pitch >= 12}
                onClick={() => onAction("Changing pitch", pitchCommands(row.id, row.pitch + 1))}
                type="button"
              >
                +
              </button>
            </span>
          ) : null}
        </div>
        {error ? (
          <div className="err" role="alert">
            <Icon name="x" />
            <div>{error}</div>
          </div>
        ) : null}
        {reason ? (
          <p className="reason" id={whyId}>
            <Icon name="info" />
            {reason}
          </p>
        ) : null}
        {hasUnsavedEdits ? (
          <div className="actions">
            <button type="button" className="btn sm" onClick={onDiscardEdits}>
              Discard edits
            </button>
          </div>
        ) : null}
      </article>
    </section>
  );
}
