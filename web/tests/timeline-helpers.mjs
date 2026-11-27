import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

// Props for rendering Timeline to static markup; `over` replaces any of them.
export function timelineProps(view, over = {}) {
  const noop = () => {};
  return {
    view,
    engine: null,
    audioVersion: 0,
    time: 0,
    onSeek: noop,
    selected: null,
    onSelect: noop,
    solo: null,
    onToggleSolo: noop,
    onPlay: noop,
    pending: { get: () => null },
    onSpansChange: noop,
    onGainCommit: noop,
    onKeepChange: noop,
    disabled: null,
    ...over,
  };
}

export const render = (Timeline, props) => renderToStaticMarkup(createElement(Timeline, props));
// Peaks for every track, as the engine would return them once decoded.
export const fakeEngine = { peaks: () => Float32Array.from({ length: 16 }, () => 0.5) };
// The markup of one lane (by source id), up to the next lane.
export const laneOf = (html, id) =>
  html.split(/(?=<div class="lane(?: sel| draft| ruler)?")/).find((part) => part.includes(`data-source="${id}"`)) ?? "";
