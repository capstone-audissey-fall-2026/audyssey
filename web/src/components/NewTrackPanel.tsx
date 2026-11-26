import { FormEvent, useId, useState } from "react";
import { METHOD_LABEL, NEW_TRACK_KINDS, newTrackCommand } from "../lib/newTrack";
import { objectColor } from "../lib/selection";
import { formatSpan } from "../lib/span";
import type { Command, Job, Method, SourceKind, Span } from "../types";
import Icon from "./Icon";

interface NewTrackPanelProps {
  job: Job;
  spans: Span[]; // edited on the timeline's New track lane
  disabled: string | null; // why creating is unavailable right now
  onRemoveSpan: (index: number) => void;
  onCancel: () => void;
  onCreate: (command: Command) => Promise<void> | void;
}

export default function NewTrackPanel({ job, spans, disabled, onRemoveSpan, onCancel, onCreate }: NewTrackPanelProps) {
  const uid = useId();
  const [name, setName] = useState("");
  const [kind, setKind] = useState<SourceKind>("sfx");
  const [description, setDescription] = useState("");
  const [picked, setPicked] = useState<Method>("separate");
  const [error, setError] = useState<string | null>(null);
  // A silent video can only generate; speech can only be separated.
  const method: Method = job.silent ? "generate" : kind === "dialogue" ? "separate" : picked;
  const speechOnSilent = job.silent && kind === "dialogue";
  const ready = !!name.trim() && !!description.trim() && spans.length > 0 && !speechOnSilent;

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError(null);
    try {
      await onCreate(newTrackCommand({ name, kind, description, method }, spans, job));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <section className="side-group" aria-label="New track">
      <h2>New track</h2>
      <form className="detail nt" style={{ ["--oc" as string]: objectColor(-1) }} onSubmit={(event) => void submit(event)}>
        <label>
          Name
          <input value={name} onChange={(e) => setName(e.target.value)} />
        </label>
        <label>
          Kind
          <select value={kind} onChange={(e) => setKind(e.target.value as SourceKind)}>
            {NEW_TRACK_KINDS.map((k) => (
              <option key={k} value={k}>
                {k}
              </option>
            ))}
          </select>
        </label>
        <label>
          Description
          <textarea rows={2} value={description} onChange={(e) => setDescription(e.target.value)} />
        </label>
        <label>
          Method
          <select value={method} onChange={(e) => setPicked(e.target.value as Method)}>
            <option value="separate" disabled={job.silent}>
              {METHOD_LABEL.separate}
            </option>
            <option value="generate" disabled={kind === "dialogue"}>
              {METHOD_LABEL.generate}
            </option>
          </select>
        </label>
        {job.silent ? <span className="hint">No original audio to separate.</span> : null}
        {kind === "dialogue" ? <span className="hint">Speech is not generated.</span> : null}
        <div className="nt-spans">
          <span id={`${uid}-spans`}>Spans</span>
          <ul aria-labelledby={`${uid}-spans`}>
            {spans.map((span, index) => (
              <li key={index}>
                <span>{formatSpan(span)}</span>
                <button aria-label={`Remove span ${formatSpan(span)}`} className="btn sm" disabled={spans.length <= 1} onClick={() => onRemoveSpan(index)} type="button">
                  Remove
                </button>
              </li>
            ))}
          </ul>
          <p className="hint">Drag on the New track lane to add a span. Drag a span to move it, or its edges to resize. Double-click a span to remove it.</p>
        </div>
        {error ? (
          <div className="err" role="alert">
            <Icon name="x" />
            <div>{error}</div>
          </div>
        ) : null}
        {disabled ? (
          <p className="reason">
            <Icon name="info" />
            {disabled}
          </p>
        ) : null}
        <div className="actions">
          <button className="btn" type="button" onClick={onCancel}>
            Cancel
          </button>
          <button className="btn primary" type="submit" disabled={!ready || disabled !== null}>
            Add track
          </button>
        </div>
      </form>
    </section>
  );
}
