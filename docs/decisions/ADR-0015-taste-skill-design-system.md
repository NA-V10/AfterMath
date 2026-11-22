# ADR-0015: Phase 6 design from the taste-skill: a dealt system for the console, the full kit for a static product page

- **Status:** Accepted (Phase 6)
- **Date:** 2026-11-22

## Context

The owner asked for Phase 6 to use [taste-skill](https://github.com/Leonxlnx/taste-skill) (MIT) for a distinctive, modern UI. The skill is written for marketing websites: a hero, one section per screen, stock photographs, scroll moments. Its own guidance says "never a generic dashboard". AFTERMATH's six screens are a dense operations console.

The owner chose the following:

- **Console:** use the skill's design system and its quality bar for the six console screens, keeping them operational.
- **Product page:** build a new public page before sign-in fully by the skill.
- **Checks:** run its dealer and checker scripts locally, with no photograph, icon or CDN downloads.
- **No hook:** do not install the skill or its Stop hook.

## Decision

### The deal

The skill's dealer, run for `software`, gave:

- **Palette:** blue-black-cornflower. Ground `#0a0d14`, surface `#131824`, ink `#e9edf3`, muted `#8891a1`, one accent `#5ab9fc`.
- **Type:** Outfit for text and headings, DM Mono for figures and codes.
- **Radius:** sharp (4, 6 and 8px).
- **Buttons:** solid.
- **Mark:** dots.

For the product page it also dealt:

- **Hero:** collage, on a sand lit ground.
- **Parts:** nav-mega, close-type, footer-dark and surface-pairs rhythm.
- **Moment:** iris-opens.

We took the first option every time, as the skill requires.

### Console (`app/(console)`, `app/globals.css`)

**Fonts and tokens**
- The dealt palette replaces the old token values, keeping the token names.
- The two violet domain colours (power and downstream) were replaced: the skill forbids violet.
- Fonts are self-hosted from `@fontsource` through `next/font/local`; no font request leaves the machine.

**One system**
- One button pair, `.btn-primary` and `.btn-secondary`, 36px (44px on touch).
- One field style and one 2px focus ring.
- Labels are sentence case at 13px/500. Nothing is set under 13px, and weights are 400 and 500 only.
- Every text token is at least 4.5:1 on every surface; body ink is at least 13:1.

**Motion**
- Button step and press, link underline draw, and a 2px lift on linked cards.
- One entrance for the page title.
- Nothing moves on scroll. Reduced-motion preferences are honoured.

### Product page

`/` is a static page at `public/landing/index.html`, rewritten from `/`.

**Build**
- Built only from the skill's kit, vendored under `public/landing/assets` (MIT licence included), plus self-hosted fonts.
- Kept separate from the console's CSS so neither style system leaks into the other.

**Content**
- Every figure and UI detail comes from a real run of this system: the storm analysis's agent results and timings, the three strategies' impact-hours, and the Riverside cascade events.
- There are no stock photographs and no invented proof.

**The required notice** "SIMULATION ENVIRONMENT — NOT CONNECTED TO LIVE INFRASTRUCTURE" appears as the hero's notice line, in the safety section and in the footer. The skill allows no bar above its header, so the notice is not a banner.

### Console moves

The Command Center moves from `/` to `/command`.

## Consequences

- (+) One consistent, higher-contrast system across six screens. The product page passes the skill's layout, copy and performance checks, except as noted in the Phase 6 report.
- (+) No runtime third-party requests. Static landing, LCP about 0.4 s in the skill's performance run.
- (−) 550 KB of vendored kit files; updates to the kit are manual.
- (−) The skill's finish gate ended **OPEN** with one heading heuristic, reported rather than worked around.
- (−) Console screens are denser than the skill's rules allow (for example, buttons are 36px on desktop). That is a deliberate trade-off for an operations tool.

## Alternatives considered

- **Literal skill on every screen:** a showcase look that hurts day-to-day use; rejected by the owner.
- **Installing the skill with its hook:** runs third-party scripts automatically at every turn; rejected.
- **Using the kit's stock photographs:** conflicts with ADR-0009 (fictional district).
