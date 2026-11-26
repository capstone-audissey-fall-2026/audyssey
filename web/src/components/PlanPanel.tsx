import { formatSpan } from "../lib/span";
import type { Job } from "../types";

// What the planner found: each source with its spans, plus what the plan check changed or dropped.
export default function PlanPanel({ job, onSeek }: { job: Job; onSeek: (time: number) => void }) {
  const kept = job.sources.filter((s) => s.status !== "skipped");
  const skipped = job.sources.filter((s) => s.status === "skipped");
  return (
    <section className="side-group" aria-label="Plan">
      <h2>Plan</h2>
      <div className="detail plan">
        {kept.length === 0 ? <p className="hint">No sound sources in the plan.</p> : null}
        <ul className="plan-list">
          {kept.map((s) => (
            <li key={s.id}>
              <div className="plan-head">
                <span className="plan-name">{s.plan.name}</span>
                <span className="badge badge-sep">{s.plan.kind}</span>
              </div>
              <p className="hint">{s.plan.description}</p>
              <div className="plan-spans">
                {s.plan.spans.map((span, i) => (
                  <button className="btn sm" data-seek={span.start} key={i} onClick={() => onSeek(span.start)} type="button">
                    {formatSpan(span)}
                  </button>
                ))}
              </div>
            </li>
          ))}
        </ul>
        {job.plan_issues.length > 0 ? (
          <>
            <h3>Plan issues</h3>
            <ul className="plan-issues">
              {job.plan_issues.map((issue, i) => (
                <li key={i}>{issue.source_name ? `${issue.source_name}: ${issue.message}` : issue.message}</li>
              ))}
            </ul>
          </>
        ) : null}
        {skipped.length > 0 ? (
          <>
            <h3>Skipped by the plan check</h3>
            <p className="hint">{skipped.map((s) => s.plan.name).join(", ")}</p>
          </>
        ) : null}
      </div>
    </section>
  );
}
