import { describe, expect, it } from "vitest";

import type { Schemas } from "@/lib/api";

import { buildFrames, lastChangeAt, statusesAt } from "./playback";

type Ev = Schemas["SimEvent"];
const change = (seq: number, t: number, wave: number, code: string, from: Ev["from_status"], to: Ev["to_status"]): Ev => ({
  seq, t_minutes: t, wave, kind: "STATUS_CHANGED", asset_code: code, from_status: from, to_status: to, details: {},
});
const other = (seq: number, t: number): Ev => ({
  seq, t_minutes: t, wave: 0, kind: "BACKUP_ENGAGED", asset_code: "B-01", from_status: null, to_status: null, details: {},
});

const events: Ev[] = [
  change(1, 0, 0, "A-01", "OPERATIONAL", "FAILED"),
  change(2, 0, 1, "B-01", "OPERATIONAL", "ON_BACKUP"),
  change(3, 0, 1, "C-01", "OPERATIONAL", "FAILED"),
  other(4, 0),
  change(5, 120, 0, "B-01", "ON_BACKUP", "FAILED"),
];
const final: Schemas["AssetState"][] = ["A-01", "B-01", "C-01", "D-01"].map((code) => ({
  code,
  condition: "INTACT",
  supply: 0,
  status: code === "D-01" ? "OPERATIONAL" : "FAILED",
  on_backup: false,
  backup_remaining_minutes: 0,
  isolated: false,
  causes: [],
}));

describe("playback", () => {
  it("groups status changes into (t, wave) frames after a baseline frame", () => {
    const frames = buildFrames(events);
    expect(frames.map((f) => [f.t, f.wave, f.changes.length])).toEqual([
      [0, -1, 0],
      [0, 0, 1],
      [0, 1, 2],
      [120, 0, 1],
    ]);
  });

  it("replays statuses frame by frame", () => {
    const frames = buildFrames(events);
    const at = (i: number) => Object.fromEntries(statusesAt(frames, i, final));
    expect(at(0)).toEqual({ "A-01": "OPERATIONAL", "B-01": "OPERATIONAL", "C-01": "OPERATIONAL", "D-01": "OPERATIONAL" });
    expect(at(2)).toMatchObject({ "A-01": "FAILED", "B-01": "ON_BACKUP", "C-01": "FAILED" });
    expect(at(3)).toMatchObject({ "B-01": "FAILED", "D-01": "OPERATIONAL" });
  });

  it("final frame equals the engine's final state", () => {
    const frames = buildFrames(events);
    const last = statusesAt(frames, frames.length - 1, final);
    for (const s of final) expect(last.get(s.code)).toBe(s.status);
  });

  it("reports the latest change per asset", () => {
    const frames = buildFrames(events);
    expect(lastChangeAt(frames, 3).get("B-01")?.seq).toBe(5);
    expect(lastChangeAt(frames, 2).get("B-01")?.seq).toBe(2);
  });
});
