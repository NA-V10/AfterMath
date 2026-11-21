"""The five agents: role, tools, and whether they run in this build (no fake capabilities)."""

from __future__ import annotations

from pydantic import BaseModel


class AgentDefinition(BaseModel):
    name: str
    role: str
    responsibilities: list[str]
    deterministic_tools: list[str]
    llm_role: str
    output: str
    available: bool
    available_from_phase: int


AGENTS: list[AgentDefinition] = [
    AgentDefinition(
        name="SENTINEL",
        role="Incident detection",
        responsibilities=[
            "Interpret free-text reports (untrusted input)",
            "Resolve mentioned facilities to assets deterministically",
            "Classify type and severity, attach evidence and confidence",
            "Ask a human when confidence is too low",
        ],
        deterministic_tools=[
            "resolve_and_validate",
            "normalise_structured_incident",
            "apply_operator_clarification",
        ],
        llm_role="Extracts quotes, type and severity from report text; never chooses asset codes.",
        output="IncidentAssessment",
        available=True,
        available_from_phase=3,
    ),
    AgentDefinition(
        name="CARTOGRAPHER",
        role="Infrastructure dependencies",
        responsibilities=[
            "Downstream reach of damaged assets",
            "Single points of failure (exact N-1)",
            "Redundancy reduced or lost",
        ],
        deterministic_tools=["dependency_analysis", "structural_criticality"],
        llm_role="Writes a briefing grounded in the dependency facts.",
        output="DependencyAnalysis",
        available=True,
        available_from_phase=3,
    ),
    AgentDefinition(
        name="ORACLE",
        role="Simulation",
        responsibilities=[
            "Run the deterministic cascade simulation for the incident",
            "Identify critical failure chains and backup deadlines",
            "Update the operational picture",
        ],
        deterministic_tools=["run_simulation", "simulation_events"],
        llm_role="Narrates simulation results; every figure is copied and grounding-checked.",
        output="SimulationSummary",
        available=True,
        available_from_phase=3,
    ),
    AgentDefinition(
        name="STRATEGIST",
        role="Recovery planning",
        responsibilities=[
            "Generate three resource-constrained recovery strategies",
            "Explain trade-offs and bottlenecks",
        ],
        deterministic_tools=["generate_strategies", "compare_strategies"],
        llm_role="Explains trade-offs; cannot alter actions or numbers.",
        output="StrategyProposal",
        available=False,
        available_from_phase=4,
    ),
    AgentDefinition(
        name="GUARDIAN",
        role="Governance & verification",
        responsibilities=[
            "Validate strategies against rules V-001..V-012",
            "Verify recovery outcomes after execution",
        ],
        deterministic_tools=["validate_strategy", "verify_execution"],
        llm_role="None for decisions; optional plain-language summary.",
        output="GovernanceReport",
        available=False,
        available_from_phase=4,
    ),
]
