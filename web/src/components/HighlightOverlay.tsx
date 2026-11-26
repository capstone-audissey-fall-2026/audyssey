import { useEffect, useState, type RefObject } from "react";
import { contentRect, type HighlightBox } from "../lib/highlight";

const pct = (v: number) => `${+(v * 100).toFixed(3)}%`;

// Draws the boxes over the picture itself, not over the letterbox bars around it.
export default function HighlightOverlay({ boxes, videoRef }: { boxes: HighlightBox[]; videoRef: RefObject<HTMLVideoElement | null> }) {
  const [rect, setRect] = useState({ x: 0, y: 0, w: 1, h: 1 });

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    const measure = () => setRect(contentRect(video.clientWidth, video.clientHeight, video.videoWidth, video.videoHeight));
    measure();
    video.addEventListener("loadedmetadata", measure);
    const observer = new ResizeObserver(measure);
    observer.observe(video);
    return () => {
      video.removeEventListener("loadedmetadata", measure);
      observer.disconnect();
    };
  }, [videoRef]);

  return (
    <div className="tracking-overlay" aria-hidden="true">
      {boxes.map(({ id, box: [x0, y0, x1, y1], color }) => (
        <div
          key={id}
          className="hl-box"
          style={{
            left: pct(rect.x + x0 * rect.w),
            top: pct(rect.y + y0 * rect.h),
            width: pct((x1 - x0) * rect.w),
            height: pct((y1 - y0) * rect.h),
            borderColor: color,
            background: `${color}33`,
          }}
        />
      ))}
    </div>
  );
}
