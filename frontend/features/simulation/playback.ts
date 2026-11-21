/**
 * Playback of a recorded simulation. The engine already computed every change; this module only
 * replays STATUS_CHANGED events in (t, wave) order. No propagation logic lives here.
 */
import type { Schemas } from "@/lib/api";
import type { FunctionalStatus } from "@/lib/queries";

type SimEvent = Schemas["SimEvent"];

export interface Frame {
  index: number;
  t: number;
  wave: number;
  /** STATUS_CHANGED events that take effect in this frame */
  changes: SimEvent[];
}

/** Frame 0 is the state before any change; then one frame per (t, wave) with status changes. */
export function buildFrames(events: SimEvent[]): Frame[] {
  const frames: Frame[] = [{ index: 0, t: 0, wave: -1, changes: [] }];
  for (const e of events) {
    if (e.kind !== "STATUS_CHANGED") continue;
    const last = frames[frames.length - 1];
    if (last.index > 0 && last.t === e.t_minutes && last.wave === e.wave) {
      last.changes.push(e);
    } else {
      frames.push({ index: frames.length, t: e.t_minutes, wave: e.wave, changes: [e] });
    }
  }
  return frames;
}

/**
 * Status of every asset after applying frames[0..index]. The starting status of each asset is
 * the `from_status` of its first change (or its final status if it never changes), so playback
 * is correct for runs that start from a non-baseline picture too.
 */
export function statusesAt(
  frames: Frame[],
  index: number,
  finalState: Schemas["AssetState"][],
): Map<string, FunctionalStatus> {
  const state = new Map<string, FunctionalStatus>(finalState.map((s) => [s.code, s.status]));
  const seen = new Set<string>();
  for (const f of frames) {
    for (const e of f.changes) {
      if (e.asset_code && !seen.has(e.asset_code) && e.from_status) {
        seen.add(e.asset_code);
        state.set(e.asset_code, e.from_status);
      }
    }
  }
  for (const f of frames.slice(1, index + 1)) {
    for (const e of f.changes) {
      if (e.asset_code && e.to_status) state.set(e.asset_code, e.to_status);
    }
  }
  return state;
}

/** Latest status-change event per asset up to a frame (for "why" explanations). */
export function lastChangeAt(frames: Frame[], index: number): Map<string, SimEvent> {
  const out = new Map<string, SimEvent>();
  for (const f of frames.slice(1, index + 1)) {
    for (const e of f.changes) if (e.asset_code) out.set(e.asset_code, e);
  }
  return out;
}
