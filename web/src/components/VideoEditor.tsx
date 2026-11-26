import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";
import { fileUrl, sendCommand } from "../api";
import { jobToView } from "../lib/adapter";
import { AudioEngine } from "../lib/audioEngine";
import { highlightChip, visibleBoxes } from "../lib/highlight";
import { newTrackSpan } from "../lib/newTrack";
import { PendingEdits } from "../lib/pendingEdits";
import { reconcileSelection, transportAction } from "../lib/selection";
import { removeSpan } from "../lib/span";
import { engineTracks, keepCommands, regenerateBlockedReason, withRender } from "../lib/trackActions";
import type { Command, Job, Span } from "../types";
import NewTrackPanel from "./NewTrackPanel";
import PlanPanel from "./PlanPanel";
import SelectedTrackPanel from "./SelectedTrackPanel";
import Stage from "./Stage";
import Timeline from "./Timeline";

interface VideoEditorProps {
  job: Job;
  busy: string | null;
  run: <T>(label: string, fn: () => Promise<T>) => Promise<T | undefined>;
  receive: (job: Job) => void;
}

// Layout glue: the stage and side panels above the timeline. Mounted per job (key = job id), so switching
// jobs stops playback and releases the old job's audio.
export default function VideoEditor({ job, busy, run, receive }: VideoEditorProps) {
  const view = useMemo(() => jobToView(job), [job]);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const [engine, setEngine] = useState<AudioEngine | null>(null);
  const [time, setTime] = useState(0);
  const [audioVersion, setAudioVersion] = useState(0);
  const [selected, setSelected] = useState<string | null>(null);
  const [solo, setSolo] = useState<string | null>(null);
  const [pending] = useState(() => new PendingEdits());
  const [, bump] = useReducer((n: number) => n + 1, 0);
  const [draft, setDraft] = useState<Span[] | null>(null);
  const disabled = regenerateBlockedReason(job, busy);

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    const next = new AudioEngine(video);
    const off = next.onTime(setTime);
    setEngine(next);
    return () => {
      off();
      next.dispose();
    };
  }, []);

  useEffect(() => {
    if (engine) engine.duration = job.duration;
  }, [engine, job.duration]);

  // Load what the tracks play; only a changed url is fetched again.
  const tracks = engineTracks(job, view);
  const tracksKey = JSON.stringify(tracks);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const stableTracks = useMemo(() => tracks, [tracksKey]);
  useEffect(() => {
    if (!engine) return;
    let current = true;
    void engine.setTracks(stableTracks).then(() => current && setAudioVersion((n) => n + 1));
    return () => {
      current = false;
    };
  }, [engine, stableTracks]);

  // Keep switches and volumes apply at once, without a server round trip.
  const viewRef = useRef(view);
  viewRef.current = view;
  const applyMix = useCallback(() => {
    if (!engine) return;
    const { rows, residual } = viewRef.current;
    for (const row of rows) {
      engine.setGain(row.id, row.gain);
      engine.setKeep(row.id, row.keep);
    }
    if (residual) {
      engine.setGain("residual", residual.gain);
      engine.setKeep("residual", residual.keep);
    }
  }, [engine]);
  useEffect(applyMix, [applyMix, view, audioVersion]);
  useEffect(() => engine?.setSolo(solo), [engine, solo]);

  useEffect(() => {
    setSelected((current) => reconcileSelection(current, view.rows.map((r) => r.id)));
  }, [view]);

  const togglePlay = () => {
    if (!engine) return;
    const action = transportAction({ previewPlaying: engine.playingOnly, videoPlaying: engine.isPlaying, soloTrackId: solo });
    if (action === "stop-preview" || action === "pause-video") engine.pause();
    else engine.play();
  };
  const playTrack = (id: string) => {
    if (!engine) return;
    if (engine.isPlaying && engine.playingOnly) engine.pause();
    else engine.playOnly(id);
  };
  const toggleRef = useRef(togglePlay);
  toggleRef.current = togglePlay;
  // Space plays and pauses, except where it belongs to the focused control.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target instanceof Element ? event.target : null;
      if (event.code === "Space" && !target?.closest("input, select, textarea, button, [role=button], [role=switch], dialog")) {
        event.preventDefault();
        toggleRef.current();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // One change at a time; commands run in order and each answer replaces the job.
  const exec = async (label: string, commands: Command[]): Promise<Job | undefined> => {
    const next = await run(label, async () => {
      let last: Job | undefined;
      for (const command of withRender(commands)) {
        last = await sendCommand(job.id, command);
        receive(last);
      }
      return last;
    });
    applyMix(); // after a failure the engine goes back to the saved mix
    return next;
  };

  const selectedRow = view.rows.find((r) => r.id === selected);
  const selectedSource = job.sources.find((s) => s.id === selected);
  const highlight =
    selectedRow && selectedSource
      ? { text: highlightChip(selectedRow, selectedSource), color: selectedSource.plan.visual_hint ? selectedRow.color : null }
      : null;

  return (
    <div className="wrap">
      <section className="stage panel" aria-label="Video">
        <Stage
          boxes={visibleBoxes(view.rows, job.sources, selected, time)}
          duration={job.duration}
          highlight={highlight}
          isPlaying={engine?.isPlaying ?? false}
          onSeek={(t) => engine?.seek(t)}
          onTogglePlay={togglePlay}
          time={time}
          videoRef={videoRef}
          videoSrc={fileUrl(job.id, job.video_path)}
        />
      </section>
      <aside className="side">
        {draft ? (
          <NewTrackPanel
            disabled={disabled}
            job={job}
            onCancel={() => setDraft(null)}
            onCreate={async (command) => {
              const next = await exec("Adding track", [command]);
              if (!next) return;
              setDraft(null);
              setSelected(next.sources.at(-1)?.id ?? null);
            }}
            onRemoveSpan={(index) => setDraft((spans) => (spans ? removeSpan(spans, index) : spans))}
            spans={draft}
          />
        ) : selectedRow ? (
          <SelectedTrackPanel
            disabled={disabled}
            error={null}
            hasUnsavedEdits={pending.dirty().length > 0}
            job={job}
            key={selectedRow.id}
            onAction={(label, commands) => {
              void exec(label, commands).then((next) => {
                if (!next) return;
                for (const c of commands) if (c.type === "reseparate") pending.discard(c.source_id);
                bump();
              });
            }}
            onDiscardEdits={() => {
              pending.discard();
              bump();
            }}
            pendingSpans={selectedRow.origin === "separated" ? pending.get(selectedRow.id) : null}
            row={selectedRow}
          />
        ) : null}
        <PlanPanel job={job} onSeek={(t) => engine?.seek(t)} />
      </aside>
      <Timeline
        audioVersion={audioVersion}
        disabled={disabled}
        draftSpans={draft ?? undefined}
        engine={engine}
        jobRunning={job.state === "running"}
        onAddTrack={() => setDraft([newTrackSpan(engine?.now() ?? time, job.duration)])}
        onDraftSpansChange={setDraft}
        onGainCommit={(id, gain) => exec("Setting volume", [{ type: "set_gain", source_id: id, gain }]).then(() => undefined)}
        onKeepChange={(id, keep) => {
          const commands = keepCommands(view, id, keep);
          for (const c of commands) if (c.type === "keep" || c.type === "drop") engine?.setKeep(c.source_id, c.type === "keep");
          void exec(keep ? "Including track" : "Excluding track", commands);
        }}
        onPlay={playTrack}
        onSeek={(t) => engine?.seek(t)}
        onSelect={(id) => id !== "residual" && setSelected(id)}
        onSpansChange={(id, spans) => {
          pending.set(id, spans);
          bump();
        }}
        onToggleSolo={(id) => setSolo((current) => (current === id ? null : id))}
        pending={pending}
        selected={selected}
        solo={solo}
        time={time}
        view={view}
      />
    </div>
  );
}
