import { BatteryLevel, Client } from "./backend";

// Steam's EBatteryACState, for its Battery icon
export const AC_DISCHARGING = 1;
export const AC_CHARGING = 2;
// what Steam passes for controllers; its battery gauge turns red at or below it
export const CRITICAL_LEVEL = 0.1;

const LEVEL_LABELS: Record<string, string> = {
  Full: "Full",
  High: "High",
  Normal: "Medium",
  Low: "Low",
};

// xone only reports a capacity level, so pick a point inside each band
const LEVEL_FRACTIONS: Record<BatteryLevel, number | null> = {
  Full: 1,
  High: 0.75,
  Normal: 0.5,
  Low: CRITICAL_LEVEL,
  Unknown: null,
};

export function batteryText(client: Client) {
  const battery = client.battery;
  if (!battery) return null;
  if (battery.no_battery) return "No batteries · USB power";
  // xone only reports a capacity level, not a percentage
  const level = LEVEL_LABELS[battery.level] ?? "Battery level unknown";
  return battery.status === "Charging" ? `${level} · Charging` : level;
}

/** How full to draw Steam's battery gauge, or null while the level is unknown. */
export function batteryFraction(client: Client) {
  const battery = client.battery;
  if (!battery) return null;
  return battery.no_battery ? 1 : LEVEL_FRACTIONS[battery.level];
}

/** Steam's AC state for the client: running off USB power counts as charging. */
export function acState(client: Client) {
  const battery = client.battery;
  return battery?.no_battery || battery?.status === "Charging" ? AC_CHARGING : AC_DISCHARGING;
}
