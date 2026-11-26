import { FormEvent, useEffect, useRef, useState } from "react";
import { ApiError, routeRequest } from "../api";
import type { JobView } from "../lib/adapter";
import { commandSentence, commandsFor, targets, type Target } from "../lib/editBar";
import { errorText } from "../lib/useJob";
import type { Command, Job } from "../types";

type Decision = Awaited<ReturnType<typeof routeRequest>>["decision"];

const NUM: Partial<Record<Command["type"], { min: number; max: number; step: number; label: string }>> = {
  set_gain: { min: 0, max: 200, step: 5, label: "New volume (%)" },
  set_pitch: { min: -12, max: 12, step: 1, label: "New pitch (semitones)" },
};
const MAX_REQUEST = 500;

interface CommandCardProps {
  decision: Command;
  view: JobView;
  editing: boolean;
  onRun: (command: Command) => void; // with the edited value, when there was one
  onEdit: () => void;
  onCancel: () => void;
}

// What the router proposed. Nothing changes until Run.
export function CommandCard({ decision, view, editing, onRun, onEdit, onCancel }: CommandCardProps) {
  const num = NUM[decision.type];
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!editing || !num) return onRun(decision);
    const raw = Number(new FormData(event.currentTarget).get("value"));
    if (!Number.isFinite(raw)) return;
    const v = Math.min(num.max, Math.max(num.min, raw));
    if (decision.type === "set_gain") onRun({ ...decision, gain: v / 100 });
    else if (decision.type === "set_pitch") onRun({ ...decision, semitones: Math.round(v) });
  };
  const value = decision.type === "set_gain" ? Math.round(decision.gain * 100) : decision.type === "set_pitch" ? decision.semitones : 0;
  return (
    <form className="nlc" onSubmit={submit}>
      <p>
        {commandSentence(decision, view)}
        {editing && num ? (
          <>
            {" "}
            <input aria-label={num.label} autoFocus className="nlnum" defaultValue={value} max={num.max} min={num.min} name="value" required step={num.step} type="number" />
          </>
        ) : null}
      </p>
      <div className="acts">
        <button className="btn primary" type="submit">Run</button>
        {!editing && num ? <button className="btn" onClick={onEdit} type="button">Edit</button> : null}
        <button className="btn" onClick={onCancel} type="button">Cancel</button>
      </div>
    </form>
  );
}

interface ClarifyCardProps {
  decision: Extract<Decision, { type: "clarify" }>;
  view: JobView;
  onPick: (target: Target) => void;
  onCancel: () => void;
}

export function ClarifyCard({ decision, view, onPick, onCancel }: ClarifyCardProps) {
  return (
    <div className="nlc">
      <p>{decision.question}</p>
      {decision.reason === "ambiguous_target" ? (
        <div className="chips">
          {targets(view).map((t) => (
            <button className="nlchip" key={t.id} onClick={() => onPick(t)} type="button">{t.name}</button>
          ))}
        </div>
      ) : null}
      <div className="acts"><button className="btn" onClick={onCancel} type="button">Cancel</button></div>
    </div>
  );
}

interface EditBarProps {
  job: Job;
  view: JobView;
  router: string | null; // "stub" turns the bar off
  disabled: string | null; // why changes are unavailable right now
  onRun: (label: string, commands: Command[]) => Promise<boolean> | boolean;
  onTarget: (sourceId: string | null) => void; // the lane the card is about
}

// Natural-language edits: the router proposes a command, the person runs it.
export default function EditBar({ job, view, router, disabled, onRun, onTarget }: EditBarProps) {
  const [text, setText] = useState("");
  const [pending, setPending] = useState(false);
  const [card, setCard] = useState<{ decision: Decision; editing: boolean } | null>(null);
  const [message, setMessage] = useState<{ text: string; error: boolean } | null>(null);
  const original = useRef("");
  const latest = useRef(0);
  useEffect(() => () => void (latest.current = -1), []); // a closed bar drops any answer still on its way
  const stub = router === "stub";
  const ok = router !== null && !stub && job.state === "ready" && disabled === null;
  const first = view.rows[0]?.name;

  const close = () => {
    setCard(null);
    onTarget(null);
  };

  const route = async (request: string, asked: string) => {
    const n = ++latest.current;
    original.current = asked;
    setPending(true);
    setMessage(null);
    close();
    try {
      const { decision } = await routeRequest(job.id, request);
      if (n !== latest.current) return;
      setCard({ decision, editing: false });
      onTarget("source_id" in decision ? decision.source_id : null);
    } catch (error) {
      if (n !== latest.current) return;
      const bad = error instanceof ApiError && error.status === 502;
      setMessage({ text: bad ? "The router's answer could not be used. Try again." : errorText(error), error: true });
    } finally {
      if (n === latest.current) setPending(false);
    }
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const request = text.trim();
    if (request && ok && !pending) void route(request, request);
  };

  const run = async (command: Command) => {
    const applied = await onRun("Applying", commandsFor(command));
    if (!applied) return;
    close();
    setText("");
    setMessage({ text: "Applied.", error: false });
  };

  const placeholder = stub
    ? "Editing by request needs the LLM router. Set AUDYSSEY_ROUTER on the server."
    : job.state !== "ready"
      ? "Available when the analysis is done."
      : `Say what to change. For example: "${first ?? "dog"} half as loud"`;
  const d = card?.decision;

  return (
    <div
      className="nlbar-wrap"
      onKeyDown={(event) => {
        if (event.key === "Escape" && card) close();
      }}
    >
      <form className="nlbar" onSubmit={submit}>
        <input
          aria-label="Say what to change"
          autoComplete="off"
          disabled={!ok || pending}
          maxLength={MAX_REQUEST}
          onChange={(event) => setText(event.target.value)}
          placeholder={placeholder}
          value={text}
        />
        <button className="btn primary" disabled={!ok || pending || !text.trim()} type="submit">
          {pending ? "Thinking…" : "Send"}
        </button>
      </form>
      <div aria-live="polite" role="status">
        {message ? <p className={message.error ? "err" : "hint"}>{message.text}</p> : null}
        {d && d.type === "none" ? (
          <div className="nlc">
            <p>That cannot be turned into an edit. Try volume, pitch, turning a track on or off, or re-separating.</p>
            <div className="acts"><button className="btn" onClick={close} type="button">Cancel</button></div>
          </div>
        ) : d && d.type === "clarify" ? (
          <ClarifyCard
            decision={d}
            onCancel={close}
            onPick={(t) => {
              const tail = ` (target: ${t.name}, ${t.id})`;
              // The API caps a request at 500 characters; trim the original, not the target.
              void route(original.current.slice(0, Math.max(0, MAX_REQUEST - tail.length)) + tail, original.current);
            }}
            view={view}
          />
        ) : d ? (
          <CommandCard decision={d} editing={card.editing} onCancel={close} onEdit={() => setCard({ decision: d, editing: true })} onRun={(c) => void run(c)} view={view} />
        ) : null}
      </div>
    </div>
  );
}
