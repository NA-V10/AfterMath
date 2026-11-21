"""Deterministic language rules for SENTINEL.

* `resolve_mentions` maps text mentions to asset codes. It is used in BOTH modes, so an LLM never
  decides which asset an incident refers to; it only proposes quotes.
* `rule_based_extraction` is SENTINEL's deterministic implementation of the extraction task.

Rules are intentionally simple and transparent; their accuracy is measured on the labelled
synthetic report corpus (data/synthetic/meridian-valley/reports).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.agents.schemas import AssetMention, Condition, IncidentExtraction, IncidentType, Severity
from app.graph.model import AssetCategory, TwinSnapshot

CODE_RE = re.compile(r"\b([A-Z]{2,5}-(?:\d{2,3}|[A-Z]{2,5}))\b")

CATEGORY_KEYWORDS: dict[AssetCategory, tuple[str, ...]] = {
    AssetCategory.GRID_SUPPLY: ("grid supply point", "supply point"),
    AssetCategory.POWER_GENERATION: ("microgrid", "solar"),
    AssetCategory.SUBSTATION: ("substation", "sub station"),
    AssetCategory.POWER_DISTRIBUTION: ("feeder",),
    AssetCategory.HOSPITAL: ("hospital", "clinic"),
    AssetCategory.TELECOM_HUB: ("telephone exchange", "exchange"),
    AssetCategory.TELECOM_TOWER: ("mast", "cell tower", "tower"),
    AssetCategory.DATA_CENTER: ("data centre", "data center"),
    AssetCategory.EMERGENCY_OPS_CENTER: (
        "emergency operations centre", "emergency operations center", "eoc",
    ),
    AssetCategory.FIRE_STATION: ("fire station",),
    AssetCategory.WATER_INTAKE: ("intake",),
    AssetCategory.WATER_TREATMENT: ("treatment works", "treatment plant", "water works"),
    AssetCategory.WATER_PUMPING: ("pumping station", "pump station"),
    AssetCategory.FUEL_DEPOT: ("fuel depot", "fuel terminal", "depot", "terminal"),
    AssetCategory.ROAD_SEGMENT: ("road", "avenue"),
    AssetCategory.BRIDGE: ("bridge",),
}  # fmt: skip

_GENERIC = {
    "the", "of", "and", "station", "works", "centre", "center", "point", "general", "community",
    "operations", "emergency", "supply", "treatment", "pumping", "fuel", "data", "fire",
    "telephone", "civic", "grid", "west", "east", "north", "south",
}  # fmt: skip

TYPE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "FLOODING": ("flood", "overtop", "inundat", "water level", "submerged", "underwater"),
    "POWER_FAILURE": (
        "substation", "blackout", "power", "outage", "transformer", "lights out", "feeder",
    ),
    "TELECOM_OUTAGE": ("telecom", "mast", "exchange", "no signal", "network", "phone", "comms"),
    "WATER_DISRUPTION": ("water main", "pumping", "treatment works", "no water", "water pressure"),
    "EQUIPMENT_FAILURE": ("fault", "malfunction", "breakdown", "equipment", "tripped"),
}  # fmt: skip

DAMAGE_CUES = (
    "explosion", "fire", "damage", "destroyed", "collapse", "flood", "underwater", "submerged",
    "failed", "failure", "tripped", "fault", "strike", "burst", "offline", "down", "closed",
    "blocked", "impassable", "outage at",
)  # fmt: skip
CONSEQUENCE_CUES = (
    "on generator",
    "running on",
    "without",
    "lost power",
    "no power",
    "on battery",
    "backup",
)
CATEGORY_INCIDENT_TYPE: dict[AssetCategory, str] = {
    AssetCategory.GRID_SUPPLY: "POWER_FAILURE",
    AssetCategory.POWER_GENERATION: "POWER_FAILURE",
    AssetCategory.SUBSTATION: "POWER_FAILURE",
    AssetCategory.POWER_DISTRIBUTION: "POWER_FAILURE",
    AssetCategory.TELECOM_HUB: "TELECOM_OUTAGE",
    AssetCategory.TELECOM_TOWER: "TELECOM_OUTAGE",
    AssetCategory.WATER_INTAKE: "WATER_DISRUPTION",
    AssetCategory.WATER_TREATMENT: "WATER_DISRUPTION",
    AssetCategory.WATER_PUMPING: "WATER_DISRUPTION",
}
SEVERE_WORDS = ("explosion", "fire", "collapse", "destroyed", "casualt", "evacuat")
MINOR_WORDS = ("minor", "brief", "flicker", "small")
DESTROYED_WORDS = ("destroyed", "collapsed", "burnt out", "burned out", "wrecked")
DEGRADED_WORDS = ("partial", "reduced", "degraded", "intermittent", "limited capacity")


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


@dataclass(frozen=True, slots=True)
class Candidate:
    code: str
    name: str
    category: AssetCategory
    full_name: str
    distinctive: frozenset[str]
    keywords: tuple[str, ...]


def candidates(snapshot: TwinSnapshot) -> list[Candidate]:
    out = []
    for a in snapshot.assets:
        if a.category is AssetCategory.DEMAND_ZONE:
            continue
        keywords = CATEGORY_KEYWORDS.get(a.category, ())
        kw_words = {w for k in keywords for w in k.split()}
        tokens = re.findall(r"[a-z]+", a.name.lower())
        distinctive = frozenset(t for t in tokens if t not in _GENERIC and t not in kw_words)
        out.append(Candidate(a.code, a.name, a.category, _norm(a.name), distinctive, keywords))
    return out


@dataclass(frozen=True, slots=True)
class Resolution:
    code: str
    name: str
    method: str
    score: float


def resolve_quote(quote: str, cands: list[Candidate]) -> list[Resolution]:
    """All plausible assets for one quote, best first. Ties are reported as ambiguity."""
    q = _norm(quote)
    if m := CODE_RE.search(quote.upper()):
        for c in cands:
            if c.code == m.group(1):
                return [Resolution(c.code, c.name, "code", 1.0)]
    exact = [c for c in cands if c.full_name in q]
    if exact:
        best = max(len(c.full_name) for c in exact)  # prefer the longest (most specific) name
        return [Resolution(c.code, c.name, "name", 1.0) for c in exact if len(c.full_name) == best]
    words = set(re.findall(r"[a-z]+", q))
    hits = [c for c in cands if c.distinctive & words and any(k in q for k in c.keywords)]
    return [
        Resolution(c.code, c.name, "keywords", 0.85) for c in sorted(hits, key=lambda c: c.code)
    ]


def _sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?;])\s+|\n+", text) if s.strip()]


def _condition(sentence: str) -> Condition:
    s = sentence.lower()
    if any(w in s for w in DESTROYED_WORDS):
        return "DESTROYED"
    if any(w in s for w in DEGRADED_WORDS):
        return "DEGRADED"
    return "DAMAGED"


def _role(sentence: str) -> str:
    """'affected' when the sentence only reports consequences for the facility."""
    s = sentence.lower()
    damage = any(c in s for c in DAMAGE_CUES)
    consequence = any(c in s for c in CONSEQUENCE_CUES)
    return "affected" if consequence and not damage else "damaged"


def _clauses(sentence: str) -> list[str]:
    """Split on commas/colons so 'lights out, X running on generator' separates roles."""
    return [c for c in re.split(r"[,:]\s+", sentence) if c.strip()]


def _phrases(sentence: str, cands: list[Candidate]) -> list[str]:
    """Candidate quotes in a sentence: explicit codes, full names, and 'distinctive word ...
    category keyword' windows of up to four words."""
    found: list[str] = [m.group(1) for m in CODE_RE.finditer(sentence)]
    low = sentence.lower()
    for c in cands:
        idx = low.find(c.full_name)
        if idx >= 0:
            found.append(sentence[idx : idx + len(c.full_name)])
    for c in cands:
        for kw in c.keywords:
            for m in re.finditer(r"\b" + re.escape(kw) + r"\b", low):
                before = list(re.finditer(r"[A-Za-z]+", sentence[: m.start()]))[-4:]
                first = next((w for w in before if w.group().lower() in c.distinctive), None)
                if first is not None:
                    found.append(sentence[first.start() : m.end()])
    # de-duplicate, keeping the longest quotes first
    unique: list[str] = []
    for f in sorted(set(found), key=lambda x: (-len(x), x)):
        if not any(f.lower() in u.lower() for u in unique):
            unique.append(f)
    return unique


def rule_based_extraction(report: str, snapshot: TwinSnapshot) -> IncidentExtraction:
    cands = candidates(snapshot)
    low = report.lower()
    mentions: list[AssetMention] = []
    for sentence in _sentences(report):
        for clause in _clauses(sentence):
            for quote in _phrases(clause, cands):
                if resolve_quote(quote, cands):
                    role = _role(clause) if _role(clause) == "affected" else _role(sentence)
                    mentions.append(
                        AssetMention(quote=quote, role=role, condition=_condition(sentence))
                    )

    cat_of = {c.code: c.category for c in cands}
    hits = {t: sum(low.count(k) for k in kws) for t, kws in TYPE_KEYWORDS.items()}
    matched = sorted((t for t, n in hits.items() if n), key=lambda t: (-hits[t], t))
    primary = [t for t in matched if t != "EQUIPMENT_FAILURE"]
    incident_type: IncidentType
    if "FLOODING" in primary:
        incident_type = "FLOODING"  # floods explain the other symptoms
    elif len(primary) >= 2:
        incident_type = "COMBINED"
    elif primary:
        incident_type = primary[0]  # type: ignore[assignment]
    else:
        # No type keywords: infer from what the damaged facilities are (the twin knows that).
        inferred = sorted(
            {
                CATEGORY_INCIDENT_TYPE.get(cat_of[r.code], "EQUIPMENT_FAILURE")
                for m in mentions
                if m.role == "damaged"
                for r in resolve_quote(m.quote, cands)[:1]
            }
        )
        if len(inferred) == 1:
            incident_type = inferred[0]  # type: ignore[assignment]
            matched = [incident_type]
        elif len(inferred) > 1:
            incident_type = "COMBINED"
            matched = inferred
        else:
            incident_type = "EQUIPMENT_FAILURE"

    severe = sum(1 for w in SEVERE_WORDS if w in low)
    severity: Severity
    if severe and ("hospital" in low or len(mentions) >= 2):
        severity = "CRITICAL"
    elif severe or len(mentions) >= 2 or incident_type in ("FLOODING", "COMBINED"):
        severity = "HIGH"
    elif any(w in low for w in MINOR_WORDS):
        severity = "LOW"
    else:
        severity = "MODERATE"

    missing = []
    if not any(m.role == "damaged" for m in mentions):
        missing.append("affected_asset")
    if not matched:
        missing.append("incident_type")
    if incident_type == "FLOODING":
        missing.append("flood_extent")
    consequences = [
        s.strip() for s in _sentences(report)
        if any(k in s.lower() for k in ("out", "lost", "without", "on generator", "no ", "down"))
    ][:5]  # fmt: skip
    return IncidentExtraction(
        incident_type=incident_type,
        severity=severity,
        asset_mentions=mentions[:10],
        reported_consequences=consequences,
        missing_information=missing,
    )
