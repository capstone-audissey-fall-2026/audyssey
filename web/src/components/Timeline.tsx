import { Fragment, memo, useEffect, useMemo, useRef, useState, type CSSProperties, type PointerEvent } from "react";
import type { AudioEngine } from "../lib/audioEngine";
import type { JobView, TrackRow } from "../lib/adapter";
import { GAIN_MAX_PERCENT, GAIN_STEP_PERCENT, gainToPercent, percentToGain } from "../lib/gain";
import type { PendingEdits } from "../lib/pendingEdits";
import { NONE_COLOR, statusView } from "../lib/selection";
import { drawSpan, moveSpan, removeSpan, resizeSpan, sortSpans } from "../lib/span";
import type { Span } from "../types";
import Icon, { STATUS_ICON } from "./Icon";

interface TimelineProps {
  view: JobView;
  engine: Pick<AudioEngine, "peaks" | "setGain"> | null;
  audioVersion?: number; // changes when decoded audio changes, so waveforms are redrawn
  time: number;
  onSeek: (time: number) => void;
  selected: string | null;
  onSelect: (id: string) => void;
  solo: string | null;
  onToggleSolo: (id: string) => void;
  onPlay: (id: string) => void;
  pending: Pick<PendingEdits, "get">;
  onSpansChange: (id: string, spans: Span[]) => void;
  onGainCommit: (id: string, gain: number) => Promise<void> | void; // id may be "residual"
  onKeepChange: (id: string, keep: boolean) => void;
  // Why changes are unavailable right now (a command or the job is running); null when they are allowed.
  disabled: string | null;
  jobRunning?: boolean;
  // The new track being drafted, drawn on its own lane below the sources.
  draftSpans?: Span[];
  onDraftSpansChange?: (spans: Span[]) => void;
  onAddTrack?: () => void;
}

type SpanDragMode = "move" | "start" | "end";
interface ActiveDrag {
  sourceId: string | "draft";
  mode: SpanDragMode | "draw";
  index: number;
  startX: number;
  laneLeft: number;
  laneWidth: number;
  spans: Span[];
}

const GENERATED_REASON = "Spans of generated tracks cannot be edited.";
const LAST_SPAN_REASON = "A track needs at least one span.";
const NO_AUDIO_REASON = "No audio yet.";
const RESIDUAL = "residual";

const pct = (v: number) => `${+(v * 100).toFixed(3)}%`;
const clamp = (value: number, min: number, max: number) => Math.min(Math.max(value, min), max);

export default function Timeline({
  view,
  engine,
  audioVersion = 0,
  time,
  onSeek,
  selected,
  onSelect,
  solo,
  onToggleSolo,
  onPlay,
  pending,
  onSpansChange,
  onGainCommit,
  onKeepChange,
  disabled,
  jobRunning = false,
  draftSpans,
  onDraftSpansChange,
  onAddTrack,
}: TimelineProps) {
  const { rows, residual } = view;
  const duration = Math.max(view.duration, 0.1);
  const [gainDraft, setGainDraft] = useState<{ id: string; percent: number } | null>(null);
  const [pickedSpan, setPickedSpan] = useState<{ id: string; index: number } | null>(null);
  const dragRef = useRef<ActiveDrag | null>(null);
  const draftRef = useRef<Span[]>([]);
  draftRef.current = draftSpans ?? [];
  const latest = useRef({ onSpansChange, onDraftSpansChange, duration });
  latest.current = { onSpansChange, onDraftSpansChange, duration };

  const spansOf = (row: TrackRow): Span[] => pending.get(row.id) ?? row.spans.map(({ start, end }) => ({ start, end }));
  const editable = (row: TrackRow) => row.spansEditable && disabled === null;
  const spanReason = (row: TrackRow) => (row.spansEditable ? disabled : GENERATED_REASON);

  const step = Math.max(1, Math.ceil(duration / 8));
  const ticks: number[] = [];
  for (let second = 0; second < duration; second += step) ticks.push(second);

  // Delete/Backspace removes the picked span, unless the key belongs to a text field.
  const pickedRow = pickedSpan ? rows.find((r) => r.id === pickedSpan.id) : undefined;
  useEffect(() => {
    if (!pickedRow || !pickedSpan || !(pickedRow.spansEditable && disabled === null)) return;
    const { id, index } = pickedSpan;
    const onKey = (event: KeyboardEvent) => {
      const target = event.target;
      const typing = target instanceof HTMLElement && (target.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName));
      if ((event.key === "Delete" || event.key === "Backspace") && !typing) {
        event.preventDefault();
        removePicked(id, index);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pickedSpan, pickedRow, disabled, pending]);

  function removePicked(id: string, index: number) {
    const row = rows.find((r) => r.id === id);
    if (!row) return;
    const spans = pending.get(id) ?? row.spans.map(({ start, end }) => ({ start, end }));
    const next = removeSpan(spans, index);
    if (next !== spans) onSpansChange(id, next);
    setPickedSpan(null);
  }

  useEffect(() => {
    const onMove = (event: globalThis.PointerEvent) => {
      const drag = dragRef.current;
      if (!drag) return;
      const { duration, onSpansChange, onDraftSpansChange } = latest.current;
      const seconds = (px: number) => (px / Math.max(drag.laneWidth, 1)) * duration;
      let next: Span[];
      if (drag.mode === "draw") {
        next = drawSpan(drag.spans, seconds(drag.startX - drag.laneLeft), seconds(event.clientX - drag.laneLeft), duration);
      } else {
        const delta = seconds(event.clientX - drag.startX);
        const mode = drag.mode;
        next = drag.spans.map((span, i) =>
          i !== drag.index ? span : mode === "move" ? moveSpan(span, delta, duration) : resizeSpan(span, mode, delta, duration),
        );
      }
      if (drag.sourceId === "draft") onDraftSpansChange?.(next);
      else onSpansChange(drag.sourceId, next);
    };
    const onUp = () => {
      const drag = dragRef.current;
      dragRef.current = null;
      // Spans stay in drag order while one is being drawn or moved; the draft is put in time order when it ends.
      if (drag?.sourceId === "draft") latest.current.onDraftSpansChange?.(sortSpans(draftRef.current));
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    window.addEventListener("pointercancel", onUp);
    return () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      window.removeEventListener("pointercancel", onUp);
    };
  }, []);

  function startDrag(event: PointerEvent<HTMLElement>, sourceId: string | "draft", spans: Span[], mode: SpanDragMode | "draw", index = -1) {
    const lane = event.currentTarget.closest(".lane-track");
    if (!(lane instanceof HTMLElement)) return;
    const rect = lane.getBoundingClientRect();
    const handle = event.target instanceof HTMLElement ? event.target.dataset.handle : undefined;
    dragRef.current = {
      sourceId,
      mode: mode === "draw" ? mode : handle === "left" ? "start" : handle === "right" ? "end" : "move",
      index,
      startX: event.clientX,
      laneLeft: rect.left,
      laneWidth: rect.width,
      spans,
    };
    event.currentTarget.setPointerCapture?.(event.pointerId);
    event.preventDefault();
    event.stopPropagation();
  }

  function seekAt(event: PointerEvent<HTMLElement>) {
    const rect = event.currentTarget.getBoundingClientRect();
    onSeek(clamp((event.clientX - rect.left) / Math.max(rect.width, 1), 0, 1) * duration);
  }

  const playhead = <span className="playhead" style={{ left: pct(clamp(time / duration, 0, 1)) }} />;
  const percentOf = (id: string, gain: number) => (gainDraft?.id === id ? gainDraft.percent : gainToPercent(gain));
  const commitGain = (id: string, saved: number, percent: number) => {
    const gain = percentToGain(percent);
    if (gain === saved) return setGainDraft(null);
    void Promise.resolve(onGainCommit(id, gain)).finally(() => setGainDraft(null));
  };
  const dragGain = (id: string, percent: number) => {
    setGainDraft({ id, percent });
    engine?.setGain(id, percentToGain(percent));
  };

  function laneControls(id: string, name: string, keep: boolean, gain: number, hasAudio: boolean) {
    return (
      <div className="ctl">
        <button
          aria-checked={keep}
          aria-label={`Include ${name} in the mix`}
          className="switch"
          disabled={disabled !== null}
          onClick={(event) => {
            event.stopPropagation();
            onKeepChange(id, !keep);
          }}
          role="switch"
          title={disabled ?? undefined}
          type="button"
        >
          <span aria-hidden="true" className="knob" />
        </button>
        <GainSlider
          disabled={disabled !== null || !hasAudio}
          label={name}
          onChange={(percent) => dragGain(id, percent)}
          onCommit={(percent) => commitGain(id, gain, percent)}
          percent={percentOf(id, gain)}
          title={disabled ?? (hasAudio ? undefined : NO_AUDIO_REASON)}
        />
        <button
          aria-label={`Play ${name}`}
          className="btn sm ico"
          disabled={!hasAudio}
          onClick={(event) => {
            event.stopPropagation();
            onPlay(id);
          }}
          title={hasAudio ? undefined : NO_AUDIO_REASON}
          type="button"
        >
          <Icon name="play" />
        </button>
        <button
          aria-label={`Solo ${name}`}
          aria-pressed={solo === id}
          className="btn sm tog"
          disabled={!hasAudio}
          onClick={(event) => {
            event.stopPropagation();
            onToggleSolo(id);
          }}
          title={hasAudio ? undefined : NO_AUDIO_REASON}
          type="button"
        >
          Solo
        </button>
      </div>
    );
  }

  return (
    <section className="tl panel" aria-label="Timeline" onDragStart={(event) => event.preventDefault()}>
      <div className="lane ruler">
        <div className="lane-label-sp" />
        <div className="lane-track" onPointerDown={seekAt} onPointerMove={(event) => event.buttons === 1 && seekAt(event)}>
          {ticks.map((second, index) => {
            const left = +((second / duration) * 100).toFixed(3);
            // A tick near the right edge hangs to its left so its label stays inside the ruler.
            return (
              <span className={`tick t${index}${left > 92 ? " end" : ""}`} key={second} style={{ left: `${left}%` }}>
                {second} s
              </span>
            );
          })}
          {playhead}
        </div>
      </div>
      {rows.length === 0 && !residual ? <div className="empty-lane">Tracks will appear here.</div> : null}
      {rows.map((row) => {
        const isSelected = row.id === selected;
        const hasAudio = row.status === "done" && row.trackPath !== null;
        const status = statusView(row, jobRunning);
        const spans = spansOf(row);
        const canEdit = editable(row);
        const reason = spanReason(row);
        return (
          <div
            className={isSelected ? "lane sel" : "lane"}
            data-source={row.id}
            key={row.id}
            onClick={() => onSelect(row.id)}
            style={{ "--oc": row.color } as CSSProperties}
          >
            <div className="lane-head">
              <button aria-current={isSelected ? "true" : "false"} className="lh-main" type="button">
                <span className="lh-name">
                  <span aria-hidden="true" className="sw" style={{ background: row.color }} />
                  {row.name}
                </span>
                <span className="lh-meta">
                  <span className={row.origin === "separated" ? "badge badge-sep" : "badge badge-gen"}>
                    {row.origin === "separated" ? "Separated" : "Generated"}
                  </span>
                  {status.label && status.label !== "Done" ? (
                    <span className={`st st-${status.tone === "run" ? "run" : status.tone === "wait" ? "queue" : "fail"}`} title={row.failure ?? undefined}>
                      <Icon name={STATUS_ICON[status.tone ?? "err"]} />
                      {status.label}
                    </span>
                  ) : null}
                </span>
              </button>
              {laneControls(row.id, row.name, row.keep, row.gain, hasAudio)}
            </div>
            <div className="lane-track" onPointerDown={seekAt} onPointerMove={(event) => event.buttons === 1 && !dragRef.current && seekAt(event)}>
              {hasAudio ? <Wave engine={engine} gain={percentToGain(percentOf(row.id, row.gain))} id={row.id} version={audioVersion} /> : null}
              {row.status === "failed" ? <span className="clip-none">{row.failure ?? "Failed."}</span> : null}
              {spans.map((span, index) => {
                const picked = pickedSpan?.id === row.id && pickedSpan.index === index;
                return (
                  <Fragment key={`${row.id}#${index}`}>
                    <button
                      aria-label={`${canEdit ? "Edit" : "View"} ${row.name} span, ${span.start.toFixed(1)} to ${span.end.toFixed(1)} s`}
                      aria-pressed={canEdit ? picked : undefined}
                      className={picked ? "ev picked" : "ev"}
                      onPointerDown={
                        canEdit
                          ? (event) => {
                              setPickedSpan({ id: row.id, index });
                              startDrag(event, row.id, spans, "move", index);
                            }
                          : undefined
                      }
                      style={{ left: pct(span.start / duration), width: pct((span.end - span.start) / duration) }}
                      tabIndex={-1}
                      title={reason ?? "Drag to move; drag an edge to resize; Delete removes it"}
                      type="button"
                    >
                      {canEdit ? (
                        <>
                          <span aria-hidden="true" className="ev-handle ev-handle-left" data-handle="left" />
                          <span aria-hidden="true" className="ev-handle ev-handle-right" data-handle="right" />
                        </>
                      ) : null}
                    </button>
                    {picked && canEdit ? (
                      <button
                        aria-label="Remove span"
                        className="ev-remove"
                        disabled={spans.length <= 1}
                        onClick={(event) => {
                          event.stopPropagation();
                          removePicked(row.id, index);
                        }}
                        onPointerDown={(event) => event.stopPropagation()}
                        style={{ left: pct(span.end / duration) }}
                        title={spans.length <= 1 ? LAST_SPAN_REASON : "Remove span (Delete)"}
                        type="button"
                      >
                        ×
                      </button>
                    ) : null}
                  </Fragment>
                );
              })}
              {playhead}
            </div>
          </div>
        );
      })}
      {residual ? (
        <div className={selected === RESIDUAL ? "lane sel" : "lane"} data-source={RESIDUAL} onClick={() => onSelect(RESIDUAL)} style={{ "--oc": NONE_COLOR } as CSSProperties} data-obj="none">
          <div className="lane-head">
            <button aria-current={selected === RESIDUAL ? "true" : "false"} className="lh-main" type="button">
              <span className="lh-name">
                <span aria-hidden="true" className="sw sw-none" />
                Rest of the original audio
              </span>
            </button>
            {laneControls(RESIDUAL, "rest of the original audio", residual.keep, residual.gain, true)}
          </div>
          <div className="lane-track" onPointerDown={seekAt} onPointerMove={(event) => event.buttons === 1 && seekAt(event)}>
            <Wave engine={engine} gain={percentToGain(percentOf(RESIDUAL, residual.gain))} id={RESIDUAL} version={audioVersion} />
            {playhead}
          </div>
        </div>
      ) : null}
      {draftSpans ? (
        <div className="lane draft" data-source="draft">
          <div className="lane-head">
            <span className="lh-name">
              <span aria-hidden="true" className="sw sw-none" />
              New track
            </span>
          </div>
          <div aria-label="New track spans" className="lane-track" onPointerDown={(event) => startDrag(event, "draft", draftSpans, "draw")} role="group" title="Drag to add a span">
            {draftSpans.map((span, index) => (
              <button
                aria-label={`New track span ${index + 1}, ${span.start.toFixed(1)} to ${span.end.toFixed(1)} s`}
                className="ev"
                key={index}
                onDoubleClick={() => onDraftSpansChange?.(removeSpan(draftSpans, index))}
                onPointerDown={(event) => startDrag(event, "draft", draftSpans, "move", index)}
                style={{ left: pct(span.start / duration), width: pct((span.end - span.start) / duration) }}
                tabIndex={-1}
                title="Drag to move; drag an edge to resize; double-click to remove"
                type="button"
              >
                <span aria-hidden="true" className="ev-handle ev-handle-left" data-handle="left" />
                <span aria-hidden="true" className="ev-handle ev-handle-right" data-handle="right" />
              </button>
            ))}
            {playhead}
          </div>
        </div>
      ) : null}
      {onAddTrack ? (
        <div className="tl-add">
          <button className="btn sm" disabled={disabled !== null || draftSpans !== undefined} onClick={onAddTrack} title={disabled ?? undefined} type="button">
            Add track
          </button>
        </div>
      ) : null}
    </section>
  );
}

interface GainSliderProps {
  label: string;
  percent: number;
  disabled: boolean;
  title?: string;
  onChange: (percent: number) => void;
  onCommit: (percent: number) => void;
}

// 0-200 % volume. `input` follows the drag; releasing the pointer or a key commits once.
export function GainSlider({ label, percent, disabled, title, onChange, onCommit }: GainSliderProps) {
  return (
    <span className="gain" title={title}>
      <input
        aria-label={`${label} volume`}
        disabled={disabled}
        max={GAIN_MAX_PERCENT}
        min={0}
        onChange={(event) => onChange(Number(event.target.value))}
        onClick={(event) => event.stopPropagation()} // the lane would otherwise select this track
        onDoubleClick={() => {
          if (percent !== 100) {
            onChange(100);
            onCommit(100);
          }
        }}
        onKeyUp={(event) => onCommit(Number(event.currentTarget.value))}
        onPointerDown={(event) => event.stopPropagation()}
        onPointerUp={(event) => onCommit(Number(event.currentTarget.value))}
        step={GAIN_STEP_PERCENT}
        type="range"
        value={percent}
      />
      <output>{percent}%</output>
    </span>
  );
}

// dB peaks of the decoded track, scaled by the volume. Memoized so the playhead does not recompute them.
const Wave = memo(function Wave({ engine, id, gain, version }: { engine: Pick<AudioEngine, "peaks"> | null; id: string; gain: number; version: number }) {
  const peaks = useMemo(() => engine?.peaks(id, 384) ?? null, [engine, id, version]);
  const points = useMemo(() => {
    if (!peaks || peaks.length === 0) return null;
    const y = (peak: number, sign: number) => (12 + sign * clamp(peak * gain, 0, 1) * 11.5).toFixed(1);
    const top = Array.from(peaks, (p, i) => `${i},${y(p, -1)}`);
    const bottom = Array.from(peaks, (p, i) => `${i},${y(p, 1)}`).reverse();
    return [...top, ...bottom].join(" ");
  }, [peaks, gain]);
  if (!points || !peaks) return null;
  return (
    <svg aria-hidden="true" className="wave" preserveAspectRatio="none" viewBox={`0 0 ${Math.max(peaks.length - 1, 1)} 24`}>
      <polygon points={points} />
    </svg>
  );
});
