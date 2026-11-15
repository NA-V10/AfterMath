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
