// Diarist view: waveform, predicted speakers and the editable ground truth on a zoomable timeline.
// Data comes from GET /api/session, every change is saved with PUT /api/annotation (see diarist/server.py).
"use strict";

const LABEL_W = 104;      // px, lane labels on the left
const OVERVIEW_H = 30;    // px, whole file with the visible window
const AXIS_H = 22;        // px, time axis
const PRED_H = 38;        // px, predicted speakers
const GAP = 6;            // px between lanes
const EDGE_PX = 6;        // px, grab distance of segment edges
const MIN_DUR = 0.05;     // s, shortest segment
const MAX_PPS = 4000;     // px per second at the highest zoom
const UNDO_MAX = 200;
const PALETTE = ["#4fa3ff", "#f2b134", "#3ccf91", "#e879c6", "#ff7a59",
                 "#a78bfa", "#2dd4bf", "#facc15", "#f87171", "#94e36b"];

const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const colors = {};
for (const name of ["bg", "panel", "line", "text", "muted", "wave", "range", "playhead", "pending", "accent"]) {
  colors[name] = css(`--${name}`);
}

const $ = (id) => document.getElementById(id);
const canvas = $("timeline");
const ctx = canvas.getContext("2d");
const audio = new Audio();

let session = null;       // GET /api/session
let wave = null;          // Int8Array, interleaved min / max envelope
let doc = { speakers: [], segments: [] };  // the annotation being edited
const ui = {
  t0: 0,                  // time at the left edge of the plot
  pps: 50,                // pixels per second
  W: 0, H: 0,
  rows: 1,                // ground-truth rows (overlapping segments go to further rows)
  predRows: 1,            // rows of the predictions
  selected: null,         // selected ground-truth segment
  range: null,            // {start, end} selected on the waveform or the predictions
  active: null,           // speaker id for new segments
  drag: null,
  playhead: 0,
  playEnd: null,          // stop playback here (playing a selection)
  dirty: true,
  overview: null,         // cached overview waveform {canvas, w, h}
};
const history = { undo: [], redo: [] };
const save = { timer: null, inflight: false, again: false };

// --- helpers -----------------------------------------------------------------

const clamp = (v, lo, hi) => Math.min(Math.max(v, lo), hi);
const plotW = () => Math.max(ui.W - LABEL_W, 1);
const X = (t) => LABEL_W + (t - ui.t0) * ui.pps;
const timeAt = (x) => ui.t0 + (x - LABEL_W) / ui.pps;
const minPps = () => plotW() / Math.max(session.duration, 0.1);
const round3 = (v) => Math.round(v * 1000) / 1000;

function fmt(t, digits = 1) {
  const m = Math.floor(t / 60);
  const s = t - 60 * m;
  return `${m}:${s.toFixed(digits).padStart(digits ? 3 + digits : 2, "0")}`;
}

function lanes() {
  const ov = { y: 0, h: OVERVIEW_H };
  const axis = { y: ov.y + ov.h + GAP, h: AXIS_H };
  const gtH = Math.max(72, Math.round(ui.H * 0.26));
  const gt = { y: ui.H - gtH - 4, h: gtH };
  const pred = { y: gt.y - GAP - PRED_H, h: PRED_H };
  const wav = { y: axis.y + axis.h, h: Math.max(pred.y - GAP - axis.y - axis.h, 20) };
  return { ov, axis, wave: wav, pred, gt };
}

const inLane = (lane, y) => y >= lane.y && y < lane.y + lane.h;

function speakerIndex(id) {
  return doc.speakers.findIndex((s) => s.id === id);
}

function colorOf(id) {
  const i = speakerIndex(id);
  return i < 0 ? colors.pending : PALETTE[i % PALETTE.length];
}

function nameOf(id) {
  const i = speakerIndex(id);
  return i < 0 ? id : doc.speakers[i].name;
}

function activeSpeaker() {
  if (speakerIndex(ui.active) < 0) ui.active = doc.speakers.length ? doc.speakers[0].id : null;
  if (ui.active === null) ui.active = addSpeaker().id;
  return ui.active;
}

function flash(text) {
  const el = $("hint");
  if (!el) return;
  el.textContent = text;
  clearTimeout(flash.timer);
  flash.timer = setTimeout(() => { el.textContent = ""; }, 3000);
}

// --- editing with undo -------------------------------------------------------

function snapshot() {
  return JSON.stringify({
    speakers: doc.speakers,
    segments: doc.segments.map((s) => ({ start: s.start, end: s.end, speaker: s.speaker })),
  });
}

function sortSegments() {
  doc.segments.sort((a, b) => a.start - b.start || a.end - b.end);
}

function commit(before) {
  if (before === snapshot()) return;
  history.undo.push(before);
  if (history.undo.length > UNDO_MAX) history.undo.shift();
  history.redo = [];
  changed();
}

function edit(fn) {
  const before = snapshot();
  fn();
  commit(before);
}

function changed() {
  sortSegments();
  scheduleSave();
  render();
}

function restore(from, to) {
  if (!from.length) return;
  to.push(snapshot());
  doc = JSON.parse(from.pop());
  ui.selected = null;
  changed();
}

const undo = () => restore(history.undo, history.redo);
const redo = () => restore(history.redo, history.undo);

function addSpeaker(name) {
  let k = 1;
  while (doc.speakers.some((s) => s.id === `N${k}`)) k++;
  const speaker = { id: `N${k}`, name: name || `Speaker ${doc.speakers.length + 1}` };
  doc.speakers.push(speaker);
  return speaker;
}

function assign(id) {
  ui.active = id;
  if (ui.selected) edit(() => { ui.selected.speaker = id; });
  else render();
}

function renameSpeaker(speaker, name) {
  name = name.trim();
  const other = doc.speakers.find((s) => s !== speaker && s.name === name);
  if (!name || name === speaker.name) {
    render();
  } else if (other) {
    const n = doc.segments.filter((s) => s.speaker === speaker.id).length;
    if (confirm(`Merge "${speaker.name}" into "${other.name}"? Its ${n} segments get speaker "${other.name}".`)) {
      edit(() => {
        for (const s of doc.segments) if (s.speaker === speaker.id) s.speaker = other.id;
        doc.speakers.splice(doc.speakers.indexOf(speaker), 1);
        if (ui.active === speaker.id) ui.active = other.id;
      });
    } else {
      render();
    }
  } else {
    edit(() => { speaker.name = name; });
  }
}

function selectIndex(i) {
  if (!doc.segments.length) return;
  const seg = doc.segments[clamp(i, 0, doc.segments.length - 1)];
  select(seg);
  ensureVisible(seg.start, seg.end);
}

function select(seg) {
  ui.selected = seg;
  ui.range = null;
  if (seg) ui.active = seg.speaker;
  render();
}

function deleteSelected() {
  const seg = ui.selected;
  if (!seg) return;
  const i = doc.segments.indexOf(seg);
  edit(() => { doc.segments.splice(i, 1); });
  ui.selected = doc.segments[Math.min(i, doc.segments.length - 1)] || null;
  render();
}

function splitSelected() {
  const seg = ui.selected;
  if (!seg) return;
  const t = ui.playhead;
  if (t <= seg.start + MIN_DUR || t >= seg.end - MIN_DUR) {
    flash("Move the playhead into the segment to split it");
    return;
  }
  edit(() => {
    doc.segments.push({ start: t, end: seg.end, speaker: seg.speaker });
    seg.end = t;
  });
}

function mergeNext() {
  const seg = ui.selected;
  if (!seg) return;
  const next = doc.segments[doc.segments.indexOf(seg) + 1];
  if (!next) {
    flash("No next segment");
    return;
  }
  edit(() => {
    seg.end = Math.max(seg.end, next.end);
    doc.segments.splice(doc.segments.indexOf(next), 1);
  });
}

// Speaker chosen by key, chip or button: relabels the range if there is one, else the selected segment.
function setSpeaker(id) {
  if (ui.range) paintRange(id);
  else assign(id);
}

// The range becomes one segment of speaker ``id`` (null: silence); ground truth there is cut away.
function paintRange(id) {
  const r = ui.range;
  let seg = null;
  edit(() => {
    const kept = [];
    for (const s of doc.segments) {
      if (s.end <= r.start || s.start >= r.end) kept.push(s);
      else {
        if (s.start < r.start - MIN_DUR) kept.push({ start: s.start, end: r.start, speaker: s.speaker });
        if (s.end > r.end + MIN_DUR) kept.push({ start: r.end, end: s.end, speaker: s.speaker });
      }
    }
    if (id !== null) {
      seg = { start: r.start, end: r.end, speaker: id };
      kept.push(seg);
      ui.active = id;
    }
    doc.segments = kept;
  });
  select(seg);
}

// Ground truth from all predictions; consecutive segments of a speaker are joined.
function copyPredictions() {
  if (doc.segments.length && !confirm("Replace the ground truth with the predictions?")) return;
  edit(() => {
    const segments = [];
    for (const p of session.predictions) {
      const last = segments[segments.length - 1];
      if (last && last.speaker === p.speaker && p.start - last.end <= session.merge_gap) last.end = Math.max(last.end, p.end);
      else segments.push({ start: p.start, end: p.end, speaker: p.speaker });
    }
    for (const id of new Set(segments.map((s) => s.speaker))) {
      if (speakerIndex(id) < 0) doc.speakers.push({ id, name: id });
    }
    doc.segments = segments;
  });
  select(null);
}

// Select the range of the next (+1) or previous (-1) predicted segment.
function selectPrediction(step) {
  const preds = session.predictions;
  if (!preds.length) return;
  const t = ui.range ? ui.range.start : ui.selected ? ui.selected.start : ui.playhead;
  let i = step > 0 ? preds.findIndex((p) => p.start > t + 1e-6) : preds.findLastIndex((p) => p.start < t - 1e-6);
  if (i < 0) i = step > 0 ? preds.length - 1 : 0;
  const p = preds[i];
  ui.selected = null;
  ui.range = { start: p.start, end: p.end };
  seek(p.start);
  ensureVisible(p.start, p.end);
  render();
}

function addRange() {
  if (!ui.range) {
    flash("Select a range on the waveform first");
    return;
  }
  const seg = { start: ui.range.start, end: ui.range.end, speaker: activeSpeaker() };
  edit(() => { doc.segments.push(seg); });
  select(seg);
}

// --- saving ------------------------------------------------------------------

function setSave(text, cls, title = "") {
  const el = $("save");
  el.textContent = text;
  el.className = `pill ${cls}`;
  el.title = title;
  save.state = cls;
}

function scheduleSave() {
  setSave("unsaved", "warn");
  clearTimeout(save.timer);
  save.timer = setTimeout(doSave, 500);
}

async function doSave() {
  if (save.inflight) {
    save.again = true;
    return;
  }
  save.inflight = true;
  setSave("saving…", "warn");
  const body = {
    audio: session.annotation.audio,
    duration: session.duration,
    speakers: doc.speakers,
    segments: doc.segments.map((s) => ({ start: round3(s.start), end: round3(s.end), speaker: s.speaker })),
  };
  try {
    const response = await fetch("/api/annotation", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!response.ok) throw new Error(`${response.status} ${await response.text()}`);
    setSave("saved", "ok");
    updateScore();
  } catch (err) {
    console.error(err);
    setSave("save failed", "bad", String(err));
  } finally {
    save.inflight = false;
    if (save.again) {
      save.again = false;
      doSave();
    }
  }
}

// The DER takes a while for long files: one request at a time, repeated if the annotation changed meanwhile.
async function updateScore() {
  if (updateScore.inflight) {
    updateScore.again = true;
    return;
  }
  updateScore.inflight = true;
  try {
    const response = await fetch("/api/score");
    if (response.ok) showScore(await response.json());
  } catch (err) {
    console.error(err);
  } finally {
    updateScore.inflight = false;
    if (updateScore.again) {
      updateScore.again = false;
      updateScore();
    }
  }
}

function showScore(score) {
  const el = $("der");
  el.hidden = !score;
  if (!score) return;
  const pct = (v) => `${(100 * v).toFixed(1)}%`;
  el.textContent = `DER ${pct(score.der)} to ${fmt(score.until, 0)}`;
  el.title = `Diarization error rate of the predictions on the labelled part (0:00 – ${fmt(score.until)}, `
    + `${score.speech.toFixed(1)} s speech):\nconfusion ${pct(score.confusion)}, `
    + `false alarm ${pct(score.false_alarm)}, missed ${pct(score.missed)}`;
}

window.addEventListener("beforeunload", (e) => {
  if (save.state !== "ok") e.preventDefault();
});

// --- playback ----------------------------------------------------------------

function seek(t) {
  ui.playhead = clamp(t, 0, session.duration);
  ui.playEnd = null;
  audio.currentTime = ui.playhead;
  ui.dirty = true;
  updateClock();
}

function play(start, end = null) {
  audio.currentTime = start;
  ui.playhead = start;
  ui.playEnd = end;
  audio.play();
}

function togglePlay() {
  if (!audio.paused) audio.pause();
  else play(ui.playhead >= session.duration - 0.01 ? 0 : ui.playhead);
}

function playSelection() {
  const sel = ui.selected || ui.range;
  if (sel) play(sel.start, sel.end);
  else togglePlay();
}

function updateClock() {
  $("clock").textContent = `${fmt(ui.playhead)} / ${fmt(session.duration)}`;
}

audio.addEventListener("play", () => { $("play").textContent = "⏸ Pause"; });
audio.addEventListener("pause", () => { $("play").textContent = "▶ Play"; ui.dirty = true; });

// --- view --------------------------------------------------------------------

function clampView() {
  ui.pps = clamp(ui.pps, minPps(), MAX_PPS);
  ui.t0 = clamp(ui.t0, 0, Math.max(session.duration - plotW() / ui.pps, 0));
  ui.dirty = true;
}

function zoomAt(t, factor) {
  const x = X(t);
  ui.pps = clamp(ui.pps * factor, minPps(), MAX_PPS);
  ui.t0 = t - (x - LABEL_W) / ui.pps;
  clampView();
}

function zoomKeys(factor) {
  const visible = ui.playhead >= ui.t0 && ui.playhead <= timeAt(ui.W);
  zoomAt(visible ? ui.playhead : timeAt(LABEL_W + plotW() / 2), factor);
}

function fit() {
  ui.pps = minPps();
  ui.t0 = 0;
  clampView();
}

function ensureVisible(start, end) {
  const span = plotW() / ui.pps;
  if (end - start > span) ui.pps = clamp(plotW() / ((end - start) * 1.2), minPps(), MAX_PPS);
  const visible = plotW() / ui.pps;
  if (start < ui.t0 || end > ui.t0 + visible) ui.t0 = (start + end) / 2 - visible / 2;
  clampView();
}

function resize() {
  const rect = canvas.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  ui.W = rect.width;
  ui.H = rect.height;
  canvas.width = Math.round(rect.width * dpr);
  canvas.height = Math.round(rect.height * dpr);
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ui.overview = null;
  if (session) clampView();
}

// --- drawing -----------------------------------------------------------------

function assignRows() {
  sortSegments();  // a segment being dragged may have moved past others
  ui.rows = packRows(doc.segments);
}

// Overlapping segments (sorted by start) go to further rows; returns the number of rows.
function packRows(segments) {
  const ends = [];
  for (const s of segments) {
    let row = ends.findIndex((e) => e <= s.start + 1e-6);
    if (row < 0) {
      row = ends.length;
      ends.push(0);
    }
    ends[row] = s.end;
    s._row = row;
  }
  return Math.max(ends.length, 1);
}

function rowRect(seg, lane, rows = ui.rows) {
  const h = lane.h / rows;
  return { y: lane.y + seg._row * h, h };
}

function draw() {
  ui.dirty = false;
  const L = lanes();
  ctx.clearRect(0, 0, ui.W, ui.H);
  assignRows();

  drawOverview(L.ov);
  drawAxis(L.axis);

  ctx.save();
  ctx.beginPath();
  ctx.rect(LABEL_W, 0, plotW(), ui.H);
  ctx.clip();
  for (const s of doc.segments) {  // ground truth behind the waveform
    ctx.fillStyle = colorOf(s.speaker) + "1f";
    ctx.fillRect(X(s.start), L.wave.y, (s.end - s.start) * ui.pps, L.wave.h);
  }
  drawWave(L.wave);
  drawPredictions(L.pred);
  drawGroundTruth(L.gt);
  if (ui.range) {
    ctx.fillStyle = colors.range;
    const y = L.wave.y;
    ctx.fillRect(X(ui.range.start), y, (ui.range.end - ui.range.start) * ui.pps, L.gt.y + L.gt.h - y);
  }
  const px = X(ui.playhead);
  ctx.fillStyle = colors.playhead;
  ctx.fillRect(px - 0.75, L.axis.y, 1.5, L.gt.y + L.gt.h - L.axis.y);
  ctx.restore();

  ctx.fillStyle = colors.muted;
  ctx.font = "12px system-ui, sans-serif";
  ctx.textBaseline = "middle";
  const label = (text, lane) => ctx.fillText(text, 10, lane.y + lane.h / 2);
  label("Overview", L.ov);
  label("Waveform", L.wave);
  label("Predicted", L.pred);
  label("Ground truth", L.gt);
}

function drawOverview(lane) {
  const w = plotW();
  if (!ui.overview || ui.overview.w !== w) {
    const off = document.createElement("canvas");
    const dpr = window.devicePixelRatio || 1;
    off.width = Math.round(w * dpr);
    off.height = Math.round(lane.h * dpr);
    const o = off.getContext("2d");
    o.scale(dpr, dpr);
    o.fillStyle = colors.muted;
    const n = wave.length / 2;
    const mid = lane.h / 2;
    for (let px = 0; px < w; px++) {
      const ia = Math.floor((px / w) * n);
      const ib = Math.max(ia + 1, Math.floor(((px + 1) / w) * n));
      let lo = 127, hi = -127;
      for (let i = ia; i < ib && i < n; i++) {
        lo = Math.min(lo, wave[2 * i]);
        hi = Math.max(hi, wave[2 * i + 1]);
      }
      if (hi < lo) continue;
      const y1 = mid - (hi / 127) * mid * 0.9;
      const y2 = mid - (lo / 127) * mid * 0.9;
      o.fillRect(px, y1, 1, Math.max(1, y2 - y1));
    }
    ui.overview = { canvas: off, w };
  }
  ctx.fillStyle = colors.bg;
  ctx.fillRect(LABEL_W, lane.y, w, lane.h);
  ctx.drawImage(ui.overview.canvas, LABEL_W, lane.y, w, lane.h);
  const scale = w / session.duration;
  for (const s of doc.segments) {
    ctx.fillStyle = colorOf(s.speaker);
    ctx.fillRect(LABEL_W + s.start * scale, lane.y + lane.h - 4, Math.max((s.end - s.start) * scale, 1), 4);
  }
  ctx.strokeStyle = colors.text;
  ctx.lineWidth = 1;
  const vx = LABEL_W + ui.t0 * scale;
  ctx.strokeRect(vx + 0.5, lane.y + 0.5, Math.max((plotW() / ui.pps) * scale - 1, 2), lane.h - 1);
  ctx.fillStyle = colors.playhead;
  ctx.fillRect(LABEL_W + ui.playhead * scale - 0.5, lane.y, 1, lane.h);
}

function drawAxis(lane) {
  const steps = [0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600];
  const step = steps.find((s) => s * ui.pps >= 70) || 3600;
  const digits = step < 0.1 ? 2 : step < 1 ? 1 : 0;
  ctx.font = "11px system-ui, sans-serif";
  ctx.textBaseline = "middle";
  ctx.strokeStyle = colors.line;
  ctx.fillStyle = colors.muted;
  const end = timeAt(ui.W);
  for (let t = Math.ceil(ui.t0 / step) * step; t <= end; t += step) {
    const x = Math.round(X(t)) + 0.5;
    ctx.beginPath();
    ctx.moveTo(x, lane.y + lane.h - 6);
    ctx.lineTo(x, ui.H);
    ctx.stroke();
    ctx.fillText(fmt(t, digits), x + 3, lane.y + lane.h / 2 - 2);
  }
}

function drawWave(lane) {
  const r = session.waveform_rate;
  const n = wave.length / 2;
  const mid = lane.y + lane.h / 2;
  const half = (lane.h / 2) * 0.95;
  ctx.fillStyle = colors.wave;
  for (let px = 0; px < plotW(); px++) {
    const ta = ui.t0 + px / ui.pps;
    let ia = Math.floor(ta * r);
    let ib = Math.max(ia + 1, Math.floor((ta + 1 / ui.pps) * r));
    if (ia >= n) break;
    ia = Math.max(ia, 0);
    ib = Math.min(ib, n);
    let lo = 127, hi = -127;
    for (let i = ia; i < ib; i++) {
      lo = Math.min(lo, wave[2 * i]);
      hi = Math.max(hi, wave[2 * i + 1]);
    }
    const y1 = mid - (hi / 127) * half;
    const y2 = mid - (lo / 127) * half;
    ctx.fillRect(LABEL_W + px, y1, 1, Math.max(1, y2 - y1));
  }
}

function drawSegment(seg, y, h, color, text, selected) {
  const x = X(seg.start);
  const w = Math.max((seg.end - seg.start) * ui.pps, 1);
  if (x > ui.W || x + w < LABEL_W) return;
  ctx.fillStyle = color;
  ctx.fillRect(x, y + 1, Math.max(w - 1, 1), h - 2);  // 1 px gap shows where adjacent segments meet
  if (selected) {
    ctx.strokeStyle = colors.text;
    ctx.lineWidth = 2;
    ctx.strokeRect(x + 1, y + 2, Math.max(w - 2, 1), h - 4);
  }
  if (w > 24) {
    ctx.save();
    ctx.beginPath();
    ctx.rect(x, y, w, h);
    ctx.clip();
    ctx.fillStyle = colors.bg;
    ctx.font = "600 12px system-ui, sans-serif";
    ctx.textBaseline = "middle";
    ctx.fillText(text, Math.max(x, LABEL_W) + 5, y + h / 2);
    ctx.restore();
  }
}

function drawPredictions(lane) {
  ctx.fillStyle = colors.bg;
  ctx.fillRect(LABEL_W, lane.y, plotW(), lane.h);
  if (!session.predictions.length) {
    ctx.fillStyle = colors.muted;
    ctx.font = "12px system-ui, sans-serif";
    ctx.textBaseline = "middle";
    ctx.fillText("No predictions (pyannote predicts speakers with a Hugging Face token, see the README)", LABEL_W + 8, lane.y + lane.h / 2);
    return;
  }
  for (const p of session.predictions) {
    const name = nameOf(p.speaker);
    const text = name === p.speaker ? p.speaker : `${p.speaker} → ${name}`;
    const r = rowRect(p, lane, ui.predRows);
    drawSegment(p, r.y, r.h, colorOf(p.speaker) + "99", text, false);
  }
}

function drawGroundTruth(lane) {
  ctx.fillStyle = colors.bg;
  ctx.fillRect(LABEL_W, lane.y, plotW(), lane.h);
  for (const s of doc.segments) {
    const r = rowRect(s, lane);
    drawSegment(s, r.y, r.h, colorOf(s.speaker), nameOf(s.speaker), s === ui.selected);
  }
}

// --- pointer input -----------------------------------------------------------

function pos(e) {
  const rect = canvas.getBoundingClientRect();
  return { x: e.clientX - rect.left, y: e.clientY - rect.top };
}

function hitGroundTruth(x, y, lane) {
  const t = timeAt(x);
  const inRow = (s) => { const r = rowRect(s, lane); return y >= r.y && y < r.y + r.h; };
  const candidates = ui.selected ? [ui.selected, ...doc.segments] : doc.segments;
  for (const s of candidates) {
    if (!inRow(s) || (s.end - s.start) * ui.pps < 3 * EDGE_PX) continue;
    if (Math.abs(x - X(s.start)) <= EDGE_PX) return { seg: s, part: "start" };
    if (Math.abs(x - X(s.end)) <= EDGE_PX) return { seg: s, part: "end" };
  }
  for (const s of candidates) {
    if (inRow(s) && t >= s.start && t <= s.end) return { seg: s, part: "body" };
  }
  return null;
}

function hitPrediction(x, y) {
  const t = timeAt(x);
  const lane = lanes().pred;
  return session.predictions.find((p) => {
    const r = rowRect(p, lane, ui.predRows);
    return t >= p.start && t <= p.end && y >= r.y && y < r.y + r.h;
  }) || null;
}

canvas.addEventListener("pointerdown", (e) => {
  if (!session || e.button !== 0) return;
  const { x, y } = pos(e);
  const L = lanes();
  const t = clamp(timeAt(x), 0, session.duration);
  canvas.setPointerCapture(e.pointerId);
  if (inLane(L.ov, y)) {
    ui.drag = { kind: "overview" };
    centerOverview(x);
  } else if (y < L.wave.y) {
    ui.drag = { kind: "pan", x0: x, t00: ui.t0 };
  } else if (x < LABEL_W) {
    ui.drag = null;
  } else if (inLane(L.gt, y)) {
    const hit = hitGroundTruth(x, y, L.gt);
    if (hit) {
      select(hit.seg);
      const kind = hit.part === "body" ? "move" : hit.part;  // start | end: resize
      ui.drag = { kind, seg: hit.seg, x0: x, t: t, orig: { ...hit.seg }, before: snapshot() };
    } else {
      ui.drag = { kind: "create", x0: x, t: t, seg: null, before: snapshot() };
    }
  } else {
    ui.drag = { kind: "range", x0: x, t: t, pred: inLane(L.pred, y) };
  }
});

function centerOverview(x) {
  const t = ((x - LABEL_W) / plotW()) * session.duration;
  ui.t0 = t - plotW() / ui.pps / 2;
  clampView();
}

canvas.addEventListener("pointermove", (e) => {
  if (!session) return;
  const { x, y } = pos(e);
  const d = ui.drag;
  if (!d) {
    updateCursor(x, y);
    return;
  }
  if (d.kind === "overview") {
    centerOverview(x);
    return;
  }
  if (d.x0 !== undefined && Math.abs(x - d.x0) > 3) d.moved = true;
  if (!d.moved) return;
  const t = clamp(timeAt(x), 0, session.duration);
  const seg = d.seg;
  switch (d.kind) {
    case "pan":
      ui.t0 = d.t00 - (x - d.x0) / ui.pps;
      clampView();
      break;
    case "range":
      ui.range = { start: Math.min(d.t, t), end: Math.max(d.t, t) };
      ui.selected = null;
      break;
    case "move": {
      const len = d.orig.end - d.orig.start;
      seg.start = clamp(d.orig.start + t - d.t, 0, session.duration - len);
      seg.end = seg.start + len;
      break;
    }
    case "start":
      seg.start = clamp(t, 0, seg.end - MIN_DUR);
      break;
    case "end":
      seg.end = clamp(t, seg.start + MIN_DUR, session.duration);
      break;
    case "create":
      if (!d.seg) {
        d.seg = { start: d.t, end: d.t, speaker: activeSpeaker() };
        doc.segments.push(d.seg);
        ui.selected = d.seg;
        ui.range = null;
      }
      d.seg.start = Math.min(d.t, t);
      d.seg.end = Math.max(d.t, t, d.seg.start + MIN_DUR);
      break;
  }
  ui.dirty = true;
  renderSelection();
});

canvas.addEventListener("pointerup", (e) => {
  const d = ui.drag;
  ui.drag = null;
  if (!d || !session) return;
  const { x, y } = pos(e);
  const t = clamp(timeAt(x), 0, session.duration);
  if (d.kind === "range" && !d.moved) {
    const p = d.pred ? hitPrediction(x, y) : null;
    ui.range = p ? { start: p.start, end: p.end } : null;
    ui.selected = p ? null : doc.segments.find((s) => t >= s.start && t <= s.end) || null;
    if (ui.selected) ui.active = ui.selected.speaker;
    seek(p ? p.start : t);
    render();
  } else if (d.kind === "range") {
    seek(ui.range.start);
    render();
  } else if (d.kind === "pan" && !d.moved) {
    seek(t);
  } else if (d.kind === "create" && !d.moved) {
    select(null);
    seek(t);
  } else if (d.before !== undefined) {
    commit(d.before);
  }
});

function updateCursor(x, y) {
  const L = lanes();
  let cursor = "default";
  if (x < LABEL_W) cursor = "default";
  else if (inLane(L.ov, y)) cursor = "pointer";
  else if (y < L.wave.y) cursor = "grab";
  else if (inLane(L.gt, y)) {
    const hit = hitGroundTruth(x, y, L.gt);
    cursor = !hit ? "crosshair" : hit.part === "body" ? "move" : "ew-resize";
  } else cursor = "text";
  canvas.style.cursor = cursor;
}

canvas.addEventListener("wheel", (e) => {
  if (!session) return;
  e.preventDefault();
  const { x } = pos(e);
  if (e.shiftKey || Math.abs(e.deltaX) > Math.abs(e.deltaY)) {
    ui.t0 += (e.deltaX || e.deltaY) / ui.pps;
    clampView();
  } else {
    zoomAt(timeAt(Math.max(x, LABEL_W)), Math.exp(-e.deltaY * 0.0015));
  }
}, { passive: false });

// --- keyboard ----------------------------------------------------------------

document.addEventListener("keydown", (e) => {
  if (!session) return;
  const tag = e.target.tagName;
  if (tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA") {
    if (e.key === "Enter" || e.key === "Escape") e.target.blur();
    return;
  }
  const ctrl = e.ctrlKey || e.metaKey;
  const key = e.key.toLowerCase();
  let handled = true;
  if (ctrl && key === "z") (e.shiftKey ? redo : undo)();
  else if (ctrl && key === "y") redo();
  else if (ctrl) handled = false;
  else if (e.key === " ") togglePlay();
  else if (e.key === "Enter") playSelection();
  else if (e.key === "Tab") selectPrediction(e.shiftKey ? -1 : 1);
  else if (e.key === "Escape") { ui.range = null; select(null); }
  else if (e.key === "ArrowLeft" && e.shiftKey) seek(ui.playhead - 1);
  else if (e.key === "ArrowRight" && e.shiftKey) seek(ui.playhead + 1);
  else if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
    let i = ui.selected ? doc.segments.indexOf(ui.selected) : -1;
    if (!ui.selected) {  // from the playhead
      const next = doc.segments.findIndex((s) => s.end > ui.playhead);
      i = (next < 0 ? doc.segments.length : next) - (e.key === "ArrowRight" ? 1 : 0);
    }
    selectIndex(i + (e.key === "ArrowRight" ? 1 : -1));
  } else if (/^[1-9]$/.test(e.key)) {
    const speaker = doc.speakers[Number(e.key) - 1];
    if (speaker) setSpeaker(speaker.id);
  } else if (e.key === "Delete" || e.key === "Backspace") {
    if (ui.range) paintRange(null);
    else deleteSelected();
  }
  else if (key === "s") splitSelected();
  else if (key === "m") mergeNext();
  else if (key === "a") addRange();
  else if (e.key === "+" || e.key === "=") zoomKeys(1.5);
  else if (e.key === "-") zoomKeys(1 / 1.5);
  else if (e.key === "0" || key === "f") fit();
  else handled = false;
  if (handled) e.preventDefault();
});

// --- panels ------------------------------------------------------------------

function render() {
  renderSpeakers();
  renderSelection();
  $("undo").disabled = !history.undo.length;
  $("redo").disabled = !history.redo.length;
  ui.dirty = true;
}

function renderSpeakers() {
  const box = $("speakers");
  if (box.contains(document.activeElement) && document.activeElement.tagName === "INPUT") return;  // typing
  box.replaceChildren();
  doc.speakers.forEach((speaker, i) => {
    const segs = doc.segments.filter((s) => s.speaker === speaker.id);
    const total = segs.reduce((sum, s) => sum + s.end - s.start, 0);
    const chip = document.createElement("div");
    chip.className = `speaker${speaker.id === ui.active ? " active" : ""}`;
    chip.title = `Click to give the selected segment or range this speaker (${i < 9 ? `key ${i + 1}` : "no key"})`;
    const key = document.createElement("div");
    key.className = "key";
    key.style.background = colorOf(speaker.id);
    key.textContent = i < 9 ? String(i + 1) : "";
    const input = document.createElement("input");
    input.value = speaker.name;
    input.title = `Speaker name (id ${speaker.id}); enter another speaker's name to merge`;
    input.addEventListener("change", () => renameSpeaker(speaker, input.value));
    input.addEventListener("blur", () => setTimeout(render));
    const stats = document.createElement("span");
    stats.className = "stats";
    stats.textContent = `${segs.length} · ${fmt(total, 0)}`;
    chip.append(key, input, stats);
    if (!segs.length) {
      const remove = document.createElement("button");
      remove.textContent = "✕";
      remove.title = "Remove this speaker";
      remove.addEventListener("click", (e) => {
        e.stopPropagation();
        edit(() => { doc.speakers.splice(doc.speakers.indexOf(speaker), 1); });
      });
      chip.append(remove);
    }
    chip.addEventListener("click", (e) => { if (e.target !== input) setSpeaker(speaker.id); });
    box.append(chip);
  });
  const add = document.createElement("button");
  add.id = "add-speaker";
  add.className = "text";
  add.textContent = "+ Speaker";
  add.title = "Add a speaker";
  add.addEventListener("click", () => {
    let speaker;
    edit(() => { speaker = addSpeaker(); });
    ui.active = speaker.id;
    render();
    const inputs = box.querySelectorAll("input");
    inputs[inputs.length - 1].select();
  });
  box.append(add);
}

function button(text, title, onclick) {
  const b = document.createElement("button");
  b.className = "text";
  b.textContent = text;
  b.title = title;
  b.addEventListener("click", onclick);
  return b;
}

function speakerButtons(current) {
  const buttons = doc.speakers.map((sp, i) => {
    const b = button(i < 9 ? `${i + 1} ${sp.name}` : sp.name, `Speaker ${sp.name}${i < 9 ? ` (key ${i + 1})` : ""}`,
      () => setSpeaker(sp.id));
    b.classList.add("speaker-button");
    if (sp.id === current) b.classList.add("current");
    b.style.setProperty("--color", colorOf(sp.id));
    return b;
  });
  buttons.push(button("+ New…", "New speaker", () => {
    const name = prompt("Name of the new speaker");
    if (!name || !name.trim()) return;
    let speaker = doc.speakers.find((sp) => sp.name === name.trim());
    if (!speaker) edit(() => { speaker = addSpeaker(name.trim()); });
    setSpeaker(speaker.id);
  }));
  return buttons;
}

function label(text) {
  const el = document.createElement("span");
  el.className = "muted";
  el.textContent = text;
  return el;
}

function renderSelection() {
  const box = $("selection");
  const hint = document.createElement("span");
  hint.id = "hint";
  hint.textContent = $("hint") ? $("hint").textContent : "";
  const info = document.createElement("span");
  info.className = "info";
  const seg = ui.selected;
  const items = [];
  if (seg) {
    info.textContent = `Segment ${fmt(seg.start, 2)} – ${fmt(seg.end, 2)} (${(seg.end - seg.start).toFixed(2)} s)`;
    items.push(
      info, label("Speaker:"), ...speakerButtons(seg.speaker), label("·"),
      button("▶ Play", "Play the segment (Enter)", () => play(seg.start, seg.end)),
      button("Split", "Split at the playhead (S)", splitSelected),
      button("Merge next", "Merge with the next segment (M)", mergeNext),
      button("Delete", "Delete the segment (Del)", deleteSelected),
    );
  } else if (ui.range) {
    const r = ui.range;
    info.textContent = `Range ${fmt(r.start, 2)} – ${fmt(r.end, 2)} (${(r.end - r.start).toFixed(2)} s)`;
    items.push(
      info, label("Speaker:"), ...speakerButtons(null),
      button("Silence", "No speech in the range: remove the ground truth there (Del)", () => paintRange(null)),
      label("·"),
      button("▶ Play", "Play the range (Enter)", () => play(r.start, r.end)),
      button(`Add overlapping`, `Add as extra segment of ${nameOf(activeSpeaker())}, keeping the others (A)`, addRange),
    );
  } else {
    info.className = "muted";
    const hasPredictions = session.predictions.length > 0;
    info.innerHTML = (hasPredictions ? "<b>Click a predicted segment</b> (or <kbd>Tab</kbd>) or <b>drag"
      : "<b>Drag") + " across the waveform</b>, "
      + "then pick the speaker (<kbd>1</kbd>–<kbd>9</kbd>) to add it to the ground truth. "
      + "Click a ground-truth segment to change it.";
    items.push(info);
    if (hasPredictions) {
      items.push(button("Copy all predictions", "Fill the ground truth with the predictions, to correct them", copyPredictions));
    }
  }
  box.replaceChildren(...items, hint);
}

$("play").addEventListener("click", togglePlay);
$("zoom-in").addEventListener("click", () => zoomKeys(1.5));
$("zoom-out").addEventListener("click", () => zoomKeys(1 / 1.5));
$("fit").addEventListener("click", fit);
$("undo").addEventListener("click", undo);
$("redo").addEventListener("click", redo);
// buttons keep no focus, so Space / Enter go to the timeline shortcuts
document.addEventListener("click", (e) => { if (e.target.tagName === "BUTTON") e.target.blur(); });

// --- main loop ---------------------------------------------------------------

function frame() {
  if (session) {
    if (!audio.paused) {
      ui.playhead = audio.currentTime;
      if (ui.playEnd !== null && ui.playhead >= ui.playEnd) {
        audio.pause();
        ui.playhead = ui.playEnd;
        ui.playEnd = null;
      }
      const visible = plotW() / ui.pps;
      if (!ui.drag && (ui.playhead > ui.t0 + visible * 0.95 || ui.playhead < ui.t0)) {
        ui.t0 = ui.playhead - visible * 0.05;
        clampView();
      }
      updateClock();
      ui.dirty = true;
    }
    if (ui.dirty) draw();
  }
  requestAnimationFrame(frame);
}

async function start() {
  const [s, w] = await Promise.all([
    fetch("/api/session").then((r) => r.json()),
    fetch("/api/waveform").then((r) => r.arrayBuffer()),
  ]);
  session = s;
  wave = new Int8Array(w);
  s.predictions.sort((a, b) => a.start - b.start || a.end - b.end);
  ui.predRows = packRows(s.predictions);  // overlapping speech predicted with two speakers
  doc = { speakers: s.annotation.speakers, segments: s.annotation.segments };
  sortSegments();
  document.title = `Diarist – ${s.name}`;
  $("file").textContent = s.name;
  audio.src = "/audio";
  audio.preload = "auto";
  resize();
  ui.pps = plotW() / Math.min(s.duration, 60);
  clampView();
  updateClock();
  setSave("saved", "ok");
  updateScore();
  render();
}

// The canvas changes size not only with the window: also when the speaker or selection bar above it
// wraps to more lines. Its drawing and the pointer hit-testing must use the same, current size.
new ResizeObserver(() => {
  resize();
  ui.dirty = true;
}).observe(canvas);
start().catch((err) => {
  console.error(err);
  setSave("load failed", "bad", String(err));
});
requestAnimationFrame(frame);
