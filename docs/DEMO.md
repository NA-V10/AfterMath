# AFTERMATH demo walkthrough (about 10 minutes)

> SIMULATION ENVIRONMENT — NOT CONNECTED TO LIVE INFRASTRUCTURE. Everything below happens inside the
> simulator, on a fictional district called Meridian Valley.

**Before you start:** start the stack (README, Quick start). Keep `DEMO_PASSWORD` from `.env` at hand.

**Two people:** the walkthrough uses two browser windows. Use a private window for the second user, because each tab keeps its own session.

## 1. The district (1 min)

**Who:** sign in as `viewer`.

Open <http://localhost:3000/command> and sign in.

1. **Infrastructure Twin:** click **SUB-02 (Riverside Substation)** on the map. The inspector, the dependency graph and the list highlight the same downstream sites: two feeders, a hospital, the water treatment works and two masts.
2. **Simulation Lab:** run **Major substation failure — Riverside**. Step through the waves.
   - At T+0, 18 sites change state.
   - The masts' batteries run out at T+2h, and the hospital's generator at T+4h.
   - **Replay** gives the identical result hash.

A viewer can explore but cannot change anything. The report form in Agent Activity tells them so.

## 2. Report an incident and let the agents analyse it (2 min)

**Who:** sign out and sign in as `operator`.

1. **Agent Activity → Report an incident → Structured.** Choose SUB-02 and give it a title.
   - Or switch to **Free-text report** and paste the first example wording. SENTINEL then extracts the damaged sites itself.
2. Select **Report & analyse** and watch the five agents run:

   | Agent | What it does |
   |---|---|
   | SENTINEL | Reads the report |
   | CARTOGRAPHER | Traces the dependencies |
   | ORACLE | Simulates the cascade |
   | STRATEGIST | Plans three strategies |
   | GUARDIAN | Checks them against 9 rules |

   Select an agent to see its result, its tool calls and its grounding check.
3. **Recovery Command** now lists the incident as *awaiting approval*. Compare the three plans:
   - **Critical services first, Maximum restoration and Balanced:** each card shows impact-hours, cost and risk.
   - **Impact over time:** the chart plots each plan against the no-action baseline.
   - **Timeline:** each plan's actions on a Gantt chart.
   - **GUARDIAN validation:** the rule list.

**Try it:** as the operator, the plan's decision box says only an approver can decide. Separation of duties also stops the person who asked for a plan from approving it.

## 3. Approve, execute and verify (3 min)

**Who:** in a private window, sign in as `approver`.

1. **Recovery Command:** open the incident, write a comment and select **Approve**. The decision is recorded against this exact plan (its content hash).
2. **Execute:** back in the operator's window, reload and select **Execute (simulated) → Confirm execution**.
   - GUARDIAN re-checks the plan against all 12 rules, including the current inventory.
   - The simulator replays it, the result is applied to the operational picture, and the result is verified.
3. **The verification panel:**
   - "Fully restored" (or the assets still down, with the reason);
   - before → after percentages by assets, criticality and population;
   - "The outcome matches the approved plan's expectation exactly".

**Try it:**
- **Reject a plan:** reject one plan of another incident. It can never be executed, and a direct API call returns 409.
- **Tamper detection:** change a plan in the database after approval. Execution refuses it (`revalidation-failed`); see `backend/tests/integration/test_governance_api.py`.

## 4. The record (2 min)

1. **Audit & Reports → Verify chain:** every action so far, by people and by agents, is in one hash-chained log, and the check reports it intact.
2. **Recovery reports → Markdown:** downloads the incident's report, built only from stored records, with the simulation notice at the top and bottom.
3. **Command Center:**
   - the decision queue;
   - the operational picture, now showing the recovery run;
   - the district baseline.

   **Reset to baseline** needs the `admin` role.

## What to look for

- **Every number comes from a deterministic engine.** Agents explain; they never compute or decide.
- **Nothing runs without a person approving that exact plan.** Every step is audited.
- **No live connections.** Nothing leaves the simulator, and the district is fictional.
