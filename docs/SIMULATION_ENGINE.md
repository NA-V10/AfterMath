# Graph & Cascading-Failure Simulation Engine

**Packages:** `app.graph`, `app.simulation` (pure, deterministic, no I/O) · Decisions: [ADR-0002](decisions/ADR-0002-networkx-graph-engine.md), [ADR-0003](decisions/ADR-0003-fixed-point-propagation.md)

## 1. Dependency model

### 1.1 Assets
Each asset has two separate kinds of state. Keeping them apart is what lets the system distinguish "repaired" from "operational":

| State | Meaning | Values | Changed by |
|---|---|---|---|
| **Physical condition** `c(a)` | Is the equipment itself intact? | `INTACT`, `DEGRADED` (partial damage; has `capacity_factor`), `DAMAGED`, `DESTROYED` | Initiating events, repair actions |
| **Functional status** `s(a)` | Is it delivering its service right now? | `OPERATIONAL`, `DEGRADED`, `ON_BACKUP`, `FAILED` | **Computed only**, never set directly |

Assets may have `backup_power_hours` (generator/battery endurance at full load). **Source assets** (`is_source=true`, e.g. grid supply points and raw-water intakes) need no upstream supply.

### 1.2 Dependencies (edges)
An edge `provider → dependent` carries:

- `service_type`: `POWER | TELECOM | WATER | FUEL | DATA | ACCESS`
- `mode`: `HARD` (needed to operate) or `SOFT` (needed for full performance)
- `redundancy_group` + `min_required` (k): the dependent needs **at least k serving providers** in the group. Two feeders with k=1 express N-1 redundancy.
- `ACCESS` edges (road segment → asset) **do not affect functional status**. The recovery planner uses them: crews must reach the asset.

Every requirement group is a k-of-n condition. A plain single dependency is the case k=1, n=1.

## 2. Functional-status evaluation: greatest fixed point over a lattice

Statuses are mapped onto a **level** lattice: `FAILED=0 < DEGRADED/ON_BACKUP=1 < OPERATIONAL=2`. A provider at level ≥ 1 is *serving*.

For an asset `a`:

```
phys(a)       = 2 if INTACT, 1 if DEGRADED, 0 if DAMAGED/DESTROYED
group(g)      = the k-th largest level among providers in g   (0 if fewer than k providers)
hard(a)       = min over HARD groups g of a:  group(g)        (2 if none)
               — if hard(a)=0 only because of POWER groups and backup_remaining(a,t) > 0:
                 treat as 1 and mark ON_BACKUP
soft(a)       = min over SOFT groups g of a:  max(group(g), 1) (2 if none)
F(L)(a)       = min(phys(a), hard(a), soft(a))
```

The functional levels `L*` are the **greatest fixed point** of `F`. They are computed by starting from "everything as good as its physical state allows" and applying `F` **synchronously** (Jacobi iteration: every asset is recomputed from the previous wave's levels) until nothing changes.

Why this design:
- **`F` is monotone on a finite lattice**, so iteration from the top terminates in at most `2·|V|` waves and reaches the unique greatest fixed point (Knaster–Tarski). That makes the final state **independent of iteration order**, so it is deterministic by construction rather than by careful sorting.
- **Cycles are handled correctly.** Substation SCADA depends softly on telecom, which depends on power. A naive BFS either loops or gives order-dependent answers. The greatest fixed point treats a mutually supporting cycle as alive unless something external kills it, which is the right semantics for "it was running before the incident".
- **Waves are meaningful.** Wave *n* is the set of assets that changed on iteration *n*: the cascade depth. The UI animates waves, and the event timeline records `(t, wave)`.

### 2.1 Refinement (Phase 1): supply level vs. displayed status

While authoring the district we found that propagating `DEGRADED` caused by **SOFT** losses would wrongly brown out the whole grid. For example, every substation loses SCADA when the telecom exchange fails, but no customer loses power. The evaluator therefore separates two things:

- **Supply level** `sup(a) ∈ {0,1,2}` is what propagates. `sup(a) = min(phys(a), min over HARD groups of the k-th largest provider supply)`. An asset ON_BACKUP supplies at full level (2) while its endurance lasts. Only **physical** degradation (`phys = 1`) reduces supply and propagates as reduced capacity.
- **Displayed status** is derived and does not propagate: `FAILED` if `sup = 0`; `ON_BACKUP` if backup is in use; `DEGRADED` if `sup = 1` or any SOFT group is unmet (its k-th largest provider supply is 0); otherwise `OPERATIONAL`.

The greatest-fixed-point argument applies unchanged to `sup` (it is monotone on a finite lattice). Status is a pure function of the fixed point.

## 3. Time: discrete-event simulation

Within one instant, propagation is the fixed-point computation above. Across time, a **discrete-event loop** advances the simulated clock:

```
queue ← initiating events (t, seq)            # priority queue ordered by (t, seq, asset_code)
while queue and t ≤ horizon:
    pop all events at the next t; apply them to physical conditions / backup timers
    L ← greatest_fixed_point(F_t)             # starts from previous levels, re-raised where
                                              # physical recovery occurred (recompute from top)
    emit StatusChanged events for each changed asset, tagged (t, wave)
    for assets newly ON_BACKUP: schedule BackupExhausted at t + backup_remaining
    for assets leaving ON_BACKUP: cancel their timers, bank the remaining endurance
```

Event kinds: `INITIATING_FAILURE`, `CONDITION_CHANGED`, `STATUS_CHANGED`, `BACKUP_ENGAGED`, `BACKUP_EXHAUSTED`, `ISOLATION_DETECTED`, `REPAIR_STARTED`, `REPAIR_COMPLETED`, `SERVICE_RESTORED`, `HORIZON_REACHED`.

The default horizon is 72 simulated hours. Time is an integer number of **minutes** to avoid floating-point drift in timers. The same loop runs recovery execution: repair completions are just events.

## 4. Initiating events (scenario inputs)

| Kind | Input | Deterministic resolution |
|---|---|---|
| Asset failure | `asset_code`, `condition`, optional `capacity_factor` | Direct |
| Area (flood) | GeoJSON polygon, `water_level_m` | Shapely intersection: assets/road segments inside the polygon with `elevation_m < water_level_m` become DAMAGED (or blocked, for roads) |
| Service outage | `service_type`, provider set | Providers become DAMAGED |
| Combined | Ordered list of the above with time offsets | Each event is queued at its offset |

Scenarios are versioned JSON files in `data/scenarios/` and are validated against a JSON Schema.

## 5. Outputs and metrics

- **Affected assets**: the final level < 2, with the initiating cause traced through the provider chain. For each affected asset we store `caused_by` = the minimal set of failed providers in the binding group, giving explainable chains.
- **Isolated components**: weakly connected components of the *serving* subgraph (HARD edges only) that contain no source asset. These are assets that are physically intact but have no possible supply path.
- **Critical-service availability**: for each service category (healthcare, emergency response, water, telecom, power) the share of criticality-weighted capacity that is serving.
- **Affected population**: demand zones (synthetic neighbourhoods modelled as sink assets of category `DEMAND_ZONE` with `population`) at level < 2, reported per service.
- **Impact score (0–100)**, versioned as `scoring_version = "1.0"`:
  ```
  W  = Σ_a crit(a)                                  over infrastructure assets
  Lc = Σ_a crit(a) · (2 − L*(a)) / 2  /  W          criticality-weighted loss
  Lp = affected_population / total_population
  Ln = |{a : L*(a) < 2}| / |V|
  impact = round(100 · (0.5·Lc + 0.3·Lp + 0.2·Ln), 2)
  ```
  The weights live in configuration and are stored on each run.
- **Result hash**: SHA-256 of the canonical JSON (sorted keys, integer minutes, rounded decimals) of `(snapshot_version, inputs, config, events, final_state)`. Replaying a run must reproduce the hash.

## 6. Criticality

- **Static criticality (0–100)**: set in the dataset from a documented category rubric (e.g. hospital 95, EOC 90, water treatment 80, substation 75…), adjusted for capacity and population served.
- **Structural criticality**: N-1 analysis. Simulate the loss of each asset alone and record its impact score. With 50 assets this is 50 fixed-point runs, about 100 ms. It is exact and needs no approximation through dominator trees (which don't model k-of-n redundancy). The cache key is `snapshot_version`.
- **Single points of failure**: assets whose N-1 run fails at least one asset with static criticality ≥ 80.

## 7. Determinism rules (enforced by tests)

1. No wall-clock time, randomness, or set/dict iteration order in decisions. Collections are sorted by `asset_code`.
2. Integer minutes. Decimals are rounded only at output boundaries.
3. Engines take an immutable `TwinSnapshot` (frozen dataclasses), never ORM objects.
4. The engine version, scoring version and snapshot version are stored on every run.

## 8. Graph traversal API (used by CARTOGRAPHER and the Twin screen)

- `upstream(a, depth=None, service_types=None)`: everything `a` transitively depends on (reverse BFS), with path and group info.
- `downstream(a, depth=None)`: everything that transitively depends on `a`. It is distinct from *impact*: downstream is structural reach, impact is what actually fails once redundancy is accounted for.
- `components()`, `sources_reachable(a)`, `single_points_of_failure()`, `validate_dataset()` (no self-loops; k ≤ |group|; consistent k per group; non-source assets have a HARD power path to a source unless they are explicitly self-powered; coordinates are within district bounds; all codes resolve).

## 9. Performance envelope

The target is 50 assets and about 150 edges, with growth headroom to about 5 000 assets. A fixed-point wave is O(E), at most 2·V waves per instant, and the number of events is bounded by about 3·V. A full 72 h simulation at the 50-asset scale is expected to take well under 50 ms in Python.

## 10. As implemented (Phase 2, engine 1.0.0, scoring 1.0)

Code: `app/simulation/{model,evaluator,engine,impact,criticality}.py`, all pure and covered by the import-linter purity contract.

Refinements over §2–§6, each covered by tests:

- **Backup engages only for a physically functional asset** (`phys > 0`). A damaged exchange does not drain its batteries. An asset that is FAILED for another reason (for example lost telecom backhaul) but whose power group is unmet keeps drawing on its backup, because the generator still runs.
- **Wave assignment.** The final state is always the greatest fixed point computed from the top. Waves are then assigned by Jacobi steps from the previous instant towards that fixed point:
  - Failures take effect at wave 0 for directly damaged assets.
  - Restorations take effect at wave 0 for assets whose own requirements are already met.
  - A *status-only* change (engaging backup, losing a SOFT supply) gets wave = 1 + the wave of its **earliest** cause.
- **Instants with no effect** (for example a stale backup timer) are skipped and produce no timeline point.
- **Isolated assets:** serving assets that have at least one HARD requirement but cannot be reached from a serving source (grid supply, generation, water intake) through serving HARD providers. In the Riverside scenario, HOS-02 on its generator is isolated until its backup is exhausted.
- **Timeline:** the first point is the pre-event baseline at t=0; the second point at t=0 is the post-event state.
- **Initial pictures:** `simulate(..., initial={code: InitialAssetState})` starts from a non-baseline state (used for restoration runs; `ASSET_RESTORED` events model completed repairs).

Measured performance on the 50-asset district: 12–16 ms per 72 h scenario; the full N-1 criticality analysis (43 simulations) takes about 0.5 s and is cached per snapshot hash.

N-1 findings on Meridian Valley v1.1.0: 14 single points of failure. They include PDN-02, whose loss takes down the telephone exchange once its 6 h backup is exhausted, and with it the data centre and the EOC.
