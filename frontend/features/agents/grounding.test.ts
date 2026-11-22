import { describe, expect, it } from "vitest";

import { foldGrounding } from "./ExecutionDetail";

describe("foldGrounding", () => {
  it("passes a single result through", () => {
    expect(foldGrounding({ ok: true, checked: true, unknown_numbers: [], unknown_asset_codes: [] })).toEqual({
      ok: true,
      unknown_numbers: [],
      unknown_asset_codes: [],
    });
  });

  it("folds one result per strategy (STRATEGIST) into one", () => {
    const folded = foldGrounding({
      a: { ok: true, unknown_numbers: [], unknown_asset_codes: [] },
      b: { ok: false, unknown_numbers: ["60.0"], unknown_asset_codes: [] },
      c: { ok: false, unknown_numbers: ["60.0"], unknown_asset_codes: ["XYZ-01"] },
    });
    expect(folded).toEqual({ ok: false, unknown_numbers: ["60.0"], unknown_asset_codes: ["XYZ-01"] });
  });

  it("treats empty or malformed input as no result", () => {
    expect(foldGrounding(null)).toBeNull();
    expect(foldGrounding({})).toBeNull();
    expect(foldGrounding({ a: "nope" })).toBeNull();
  });
});
