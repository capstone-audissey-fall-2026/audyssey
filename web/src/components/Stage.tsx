import type { RefObject } from "react";
import type { HighlightBox } from "../lib/highlight";
import HighlightOverlay from "./HighlightOverlay";
import Icon from "./Icon";

interface StageProps {
  videoSrc: string;
  duration: number;
  time: number;
  isPlaying: boolean;
  onTogglePlay: () => void;
  onSeek: (time: number) => void;
  boxes: HighlightBox[];
  // Chip text and swatch colour; a null colour means the source has no on-screen location.
  highlight: { text: string; color: string | null } | null;
  videoRef: RefObject<HTMLVideoElement | null>;
}

export default function Stage({ videoSrc, duration, time, isPlaying, onTogglePlay, onSeek, boxes, highlight, videoRef }: StageProps) {
  return (
    <>
      <div className="stage-view">
        <div className="video-box">
          <video ref={videoRef} src={videoSrc} muted playsInline preload="auto" onClick={onTogglePlay} />
          <HighlightOverlay boxes={boxes} videoRef={videoRef} />
          {highlight ? (
            <p className="chip">
              <span
                aria-hidden="true"
                className={highlight.color ? "sw" : "sw sw-none"}
                style={highlight.color ? { background: highlight.color } : undefined}
              />
              {highlight.text}
            </p>
          ) : null}
        </div>
      </div>
      <div className="transport">
        <button aria-label={isPlaying ? "Pause video" : "Play video"} className="btn ico" onClick={onTogglePlay} type="button">
          <Icon name={isPlaying ? "pause" : "play"} />
        </button>
        <input
          aria-label="Position"
          aria-valuetext={`${time.toFixed(2)} seconds`}
          max={duration}
          min="0"
          onChange={(event) => onSeek(Number(event.target.value))}
          step="0.01"
          type="range"
          value={time}
        />
        <span className="time">{`${time.toFixed(2)} s / ${duration.toFixed(2)} s`}</span>
      </div>
    </>
  );
}
