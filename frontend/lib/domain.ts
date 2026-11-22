/** Presentation metadata for domain enums. No business logic lives here. */
import type { AssetCategory, PhysicalCondition } from "@/lib/queries";

export type Domain =
  | "power"
  | "telecom"
  | "water"
  | "health"
  | "emergency"
  | "data"
  | "fuel"
  | "transport"
  | "zone";

export const DOMAIN_COLOR: Record<Domain, string> = {
  power: "#f2cf63",
  telecom: "#39c5cf",
  water: "#4493f8",
  health: "#ee6fae",
  emergency: "#f2836b",
  data: "#7d8cf5",
  fuel: "#b8a582",
  transport: "#8b949e",
  zone: "#6e7681",
};

export const DOMAIN_LABEL: Record<Domain, string> = {
  power: "Power",
  telecom: "Telecom",
  water: "Water",
  health: "Healthcare",
  emergency: "Emergency services",
  data: "Data",
  fuel: "Fuel",
  transport: "Transport",
  zone: "Demand zones",
};

interface CategoryMeta {
  label: string;
  domain: Domain;
  glyph: string;
}

export const CATEGORY: Record<AssetCategory, CategoryMeta> = {
  GRID_SUPPLY: { label: "Grid supply point", domain: "power", glyph: "G" },
  POWER_GENERATION: { label: "Generation", domain: "power", glyph: "P" },
  SUBSTATION: { label: "Substation", domain: "power", glyph: "S" },
  POWER_DISTRIBUTION: { label: "Distribution feeder", domain: "power", glyph: "D" },
  HOSPITAL: { label: "Hospital", domain: "health", glyph: "H" },
  TELECOM_HUB: { label: "Telecom exchange", domain: "telecom", glyph: "X" },
  TELECOM_TOWER: { label: "Telecom mast", domain: "telecom", glyph: "T" },
  DATA_CENTER: { label: "Data centre", domain: "data", glyph: "C" },
  EMERGENCY_OPS_CENTER: { label: "Emergency ops centre", domain: "emergency", glyph: "E" },
  FIRE_STATION: { label: "Fire station", domain: "emergency", glyph: "F" },
  WATER_INTAKE: { label: "Water intake", domain: "water", glyph: "I" },
  WATER_TREATMENT: { label: "Water treatment", domain: "water", glyph: "W" },
  WATER_PUMPING: { label: "Pumping station", domain: "water", glyph: "U" },
  FUEL_DEPOT: { label: "Fuel depot", domain: "fuel", glyph: "L" },
  ROAD_SEGMENT: { label: "Road segment", domain: "transport", glyph: "R" },
  BRIDGE: { label: "Bridge", domain: "transport", glyph: "B" },
  DEMAND_ZONE: { label: "Demand zone", domain: "zone", glyph: "Z" },
};

export const DOMAIN_ORDER: Domain[] = [
  "power", "telecom", "water", "health", "emergency", "data", "fuel", "transport", "zone",
];

export function categoriesByDomain(): [Domain, AssetCategory[]][] {
  return DOMAIN_ORDER.map((d) => [
    d,
    (Object.keys(CATEGORY) as AssetCategory[]).filter((c) => CATEGORY[c].domain === d),
  ]);
}

export function categoryColor(category: AssetCategory): string {
  return DOMAIN_COLOR[CATEGORY[category].domain];
}

export const CONDITION: Record<PhysicalCondition, { label: string; color: string }> = {
  INTACT: { label: "Intact", color: "#3fb950" },
  DEGRADED: { label: "Degraded", color: "#d29922" },
  DAMAGED: { label: "Damaged", color: "#f85149" },
  DESTROYED: { label: "Destroyed", color: "#f85149" },
};

export const SERVICE_LABEL: Record<string, string> = {
  POWER: "Power",
  TELECOM: "Telecom",
  WATER: "Water",
  FUEL: "Fuel",
  DATA: "Data",
  HEALTHCARE: "Healthcare",
  ACCESS: "Road access",
};

export function formatNumber(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined) return "—";
  return value.toLocaleString("en-GB", { maximumFractionDigits: digits });
}

export const STATUS: Record<
  "OPERATIONAL" | "DEGRADED" | "ON_BACKUP" | "FAILED",
  { label: string; color: string; rank: number }
> = {
  OPERATIONAL: { label: "Operational", color: "#3fb950", rank: 0 },
  DEGRADED: { label: "Degraded", color: "#d29922", rank: 1 },
  ON_BACKUP: { label: "On backup", color: "#e3b341", rank: 2 },
  FAILED: { label: "Failed", color: "#f85149", rank: 3 },
};

export function formatMinutes(minutes: number): string {
  if (minutes < 60) return `T+${minutes}m`;
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return m ? `T+${h}h${String(m).padStart(2, "0")}` : `T+${h}h`;
}
