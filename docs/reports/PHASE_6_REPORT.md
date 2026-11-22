# Phase 6 Report: Complete Frontend

**Date:** 2026-11-22 · **Status:** complete. The console has a new design system and the project has a public product page, both from the owner-requested [taste-skill](https://github.com/Leonxlnx/taste-skill) ([ADR-0015](../decisions/ADR-0015-taste-skill-design-system.md)).

## Decisions taken with the owner

The skill builds marketing websites, not dashboards. The owner chose:

- **Console:** use the skill's design system and its checks for the six console screens, keeping them operational.
- **Product page:** a new public page before sign-in, built fully by the skill.
- **Offline checks:** run its scripts locally with no downloads, and do not install the skill or its hook.

## Delivered

### Console design system

**Applied to all six screens**
- **The deal:** palette blue-black-cornflower, type Outfit + DM Mono, radius sharp, one sky-blue accent `#5ab9fc`.
- **Fonts:** self-hosted through `next/font/local` from `@fontsource`. No font request leaves the browser.
- **One system:**
  - one button pair (`.btn-primary`/`.btn-secondary`) and one field style;
  - one 2px focus ring;
  - sentence-case labels at 13px/500, nothing under 13px, weights 400 and 500 only.
- **No violet:** the violet "power" and "downstream" colours were replaced.
- **Contrast,** measured: every text token is at least 4.5:1 on every surface, body ink 13–16.5:1, accent 9:1.
- **Motion:**
  - button step and press;
  - link underline draw;
  - a 2px lift on linked cards;
  - one title entrance per screen.

  Nothing moves on scroll, and reduced motion is respected.

**New shell**
- One header carrying the required simulation notice, the dots mark, the API state, and the user with role and sign-out.
- A rail nav whose current page gets an accent bar.
- A `PageHeader` with the screen title and one plain line on every screen.

**Screens completed**
- **Command Center** (now `/command`): a "Needs a decision" queue that links straight to each incident (`/recovery#incident=…`), open and recovered counts, system state, the operational picture and the district baseline.
- **Audit & Reports:** a **Recovery reports** panel with Markdown downloads, shortened IDs with the full value on hover, and actor labels without the doubled prefix.
- **Recovery Command:**
  - cards show the policy name first, then lifecycle and recommendation badges;
  - one Approve primary button, with Reject as the secondary;
  - the deep link to an incident.
- **Twin:** controls in the header, the legend on its own row, and map grounds in the new palette.

### Product page (`/`, `public/landing/index.html`)

**Build**
- A static page built only from the skill's kit, vendored with its MIT licence, and kept apart from the console's CSS.
- Structure: hero, app frame, cascade split, three steps, a safety statement with the iris-opens moment, FAQ, then the close and footer.

**Real data only**
- The five agents' actual summaries and timings for the storm (3.3 s in total).
- The three strategies' impact-hours: 2,315, 2,386 and 2,568, against 10,691 with no action.
- The Riverside cascade: 18 sites change state in 4 waves, the masts fail at T+2h, the hospital at T+4h.
- The verification figures of a real recovered run.
- No stock photographs, no invented proof.

**The simulation notice** is the hero's notice line, appears again in the safety section and the footer, and is checked by E2E.

## Checks (actual results)

### Product page, with the skill's own scripts (headless Edge, offline)

| Check | Result |
|---|---|
| `copy-lint.mjs` | 0 FAIL, 0 WARN, 449 words |
| `layout/check.mjs` at 1440, 1024, 820, 768 and 390 | pass, no findings |
| `consistency.mjs` | 44 FAIL in the first run, 13 after three rounds of fixes |
| `perf.mjs` | 0 FAIL, 3 WARN: LCP 376 ms, no layout shift, 0 blocking time, 61 KB of fonts, no WebGL |
| **`gate.mjs`** | **GATE: OPEN 1** (rounds used up) |

**What the fix rounds changed**
- Headings now name a thing or carry a real number.
- Body text uses full ink for 7:1 contrast.
- Gaps between sections are even.
- Two screens on tablet and phone where needed.
- A phone action bar was added.
- The footer row now reaches the right edge.

**The open FAIL**
- **`copy-headings` on the FAQ subheadings:** "Connects to no live system", "Runs without an AI provider", "Needs a second person to approve". copy.md allows FAQ entries to be questions; the noun heuristic doesn't recognise these.
- I wrote a waiver, but its target didn't match the reported selector, so the finding is **open, not waived**.

**Not re-checked after the last gate run**
The gate's three rounds were used, so these rhythm FAILs from the last full `consistency.mjs` run were not re-checked afterwards:
- a flush edge on the iris-opens moment's own element at 820;
- section-gap and section-height findings at 768 and 390.

They should be re-run in Phase 7.

### Console and the whole frontend

| Suite | Result |
|---|---|
| tsc / ESLint | clean / clean. The vendored kit is excluded from lint. |
| Vitest | 16 passed |
| `next build` | success. The routes are `/command`, `/twin`, `/lab`, `/recovery`, `/agents` and `/audit`; `/` is rewritten to the static page. |
| Playwright E2E (Edge) | **17 passed** (16 updated plus the new product-page journey). The governance and twin specs were re-run after the last layout change: 7 passed. |
| Backend | unchanged in this phase (206 passed at the end of Phase 5) |

### E2E journeys (TESTING_STRATEGY §5)

| Journey | Status |
|---|---|
| 1. Twin | pass |
| 2. Lab | pass |
| 3. Full demo | pass, in `agents.spec` and `governance.spec` |
| 4. Governance negatives | pass |
| 5. Misconfigured LLM provider | **not in E2E**. Backend integration tests cover the fallback; a browser test would need the API restarted with a broken provider. |

## Open items / known gaps

- **The skill's gate is open.** One FAQ heading heuristic, plus tablet and phone rhythm findings not re-checked after the gate's rounds ran out (see above).
- **Console density trade-off.** Console buttons are 36px on desktop (the skill asks for 44), and data tables use 14px. Both are deliberate for an operations console. Touch devices get 44px buttons.
- **Vendored kit.** 550 KB of the kit under `public/landing/assets` is updated by hand.
- **Checker state in the repo.** `frontend/.taste-skill/` holds the deal history and waivers in git. Browser profiles and shots are ignored.
- **Phase 7:**
  - CI for these checks;
  - an import-contract check that runs on this host;
  - E2E for the provider-outage journey.
