import { statusLine } from "../lib/status";
import type { Job, Method } from "../types";
import Icon, { type IconName } from "./Icon";

interface TopBarProps {
  job: Job | null;
  busy: string | null;
  error: string | null;
  method: Method; // the choice before the job starts
  onMethodChange: (method: Method) => void;
  onOpen: () => void;
  onStart: () => void;
  onExport: () => void;
}

const TONE_ICON: Record<"idle" | "run" | "done" | "fail", IconName> = { idle: "info", run: "spin", done: "check", fail: "x" };
const METHODS = [
  { method: "generate", label: "Generate" },
  { method: "separate", label: "Separate" },
] as const;

export default function TopBar({ job, busy, error, method, onMethodChange, onOpen, onStart, onExport }: TopBarProps) {
  const status = error ? { tone: "fail" as const, text: error, progress: null } : statusLine(job, busy);
  const choosing = job?.state === "new";
  const chosen: Method = job?.silent ? "generate" : method;
  return (
    <header className="top">
      <div className="brand">
        <h1>Audyssey</h1>
        {job ? <span className="in-badge">{job.silent ? "Silent video" : "Original audio"}</span> : null}
      </div>
      <div className="top-btns">
        <button className="btn" type="button" onClick={onOpen}>
          Open video
        </button>
      </div>
      <div className={`status st-k-${status.tone === "idle" ? "done" : status.tone}`} role="status">
        <Icon name={TONE_ICON[status.tone]} />
        <div className="status-t">
          <span>{status.text}</span>
          {status.tone !== "run" ? null : status.progress === null ? (
            <div className="bar indeterminate" role="progressbar" aria-label="Progress">
              <i />
            </div>
          ) : (
            <div className="bar" role="progressbar" aria-label="Progress" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(status.progress * 100)}>
              <i style={{ width: `${Math.round(status.progress * 100)}%` }} />
            </div>
          )}
        </div>
      </div>
      {job && choosing ? (
        <div className="mode-pick">
          <div className="modes" role="radiogroup" aria-label="Audio method">
            {METHODS.map(({ method: m, label }) => {
              const noAudio = m === "separate" && job.silent;
              return (
                <button
                  key={m}
                  type="button"
                  role="radio"
                  aria-checked={chosen === m}
                  className="btn"
                  disabled={busy !== null || noAudio}
                  aria-describedby={noAudio ? "no-audio-why" : undefined}
                  onClick={() => onMethodChange(m)}
                >
                  {label}
                </button>
              );
            })}
          </div>
          {job.silent ? (
            <span className="mode-why" id="no-audio-why">
              No original audio to separate.
            </span>
          ) : null}
        </div>
      ) : job?.method ? (
        <span className="in-badge">{job.method === "separate" ? "Separate" : "Generate"}</span>
      ) : null}
      {job && choosing ? (
        <button className="btn primary" type="button" disabled={busy !== null} onClick={onStart}>
          {chosen === "separate" ? "Separate audio" : "Generate audio"}
        </button>
      ) : null}
      {job && !choosing ? (
        <button className="btn" type="button" disabled={job.state !== "ready" || busy !== null} onClick={onExport}>
          Export
        </button>
      ) : null}
    </header>
  );
}
