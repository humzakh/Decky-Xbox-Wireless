import { callable, toaster } from "@decky/api";

export type BatteryLevel = "Unknown" | "Low" | "Normal" | "High" | "Full";

export interface Battery {
  status: string;
  level: BatteryLevel;
  no_battery: boolean;
}

export interface Led {
  name: string;
  brightness: number;
  max_brightness: number;
  mode: number;
  // what xone sets on connect; also where reset_led puts it back
  default_brightness: number;
}

export interface Client {
  id: string;
  kind: "gamepad" | "headset" | "chatpad" | "guitar" | "drums" | "unknown";
  gip_class: string | null;
  driver: string | null;
  vendor_id: string | null;
  product_id: string | null;
  version: string | null;
  serial: string | null;
  // stable identity used for per-controller settings
  key: string | null;
  // announced by the controller itself, no hardware attached
  phantom: boolean;
  name: string;
  battery: Battery | null;
  led: Led | null;
  // game/chat dial of a headset, 0 (all game, turned forward) to 100 (all chat); null without one
  chat_mix: number | null;
}

export interface Device {
  adapter: string;
  adapter_id: number;
  connecting: boolean;
  // attachments left over while xone removes the main client
  partial: boolean;
  clients: Client[];
  slot: number | null;
  interface?: string;
}

export interface Dongle {
  id: string;
  product_id: string;
  model: string;
  serial: string | null;
  pairing: boolean;
  active_clients: number;
  devices: Device[];
  // announcing clients that never finish connecting; only unplugging it clears this
  stuck: boolean;
}

// shown for a stuck dongle
export const STUCK_TITLE = "Adapter stopped responding";
export const STUCK_FIX = "Unplug it, wait 10 seconds and plug it back in.";

export interface State {
  driver_loaded: boolean;
  dongles: Dongle[];
  wired: Device[];
  pairing_started: Record<string, number>;
  pairing_timeout: number;
}

export interface Settings {
  notify_connect: boolean;
  notify_low_battery: boolean;
  chat_mix: boolean;
  leds: Record<string, { brightness?: number; mode?: number }>;
}

export interface Result {
  ok: boolean;
  error?: string | null;
}

export function reportError(res: Result) {
  if (!res.ok) toaster.toast({ title: "Xbox Wireless", body: res.error ?? "Request failed" });
}

export const getState = callable<[], State>("get_state");
export const getSettings = callable<[], Settings>("get_settings");
export const setSetting = callable<[key: keyof Settings, value: unknown], Result>("set_setting");
export const setPairing = callable<[dongleId: string, enabled: boolean], Result>("set_pairing");
export const powerOff = callable<[dongleId: string, slot: number], Result>("power_off");
export const setLed = callable<[clientId: string, brightness: number | null, mode: number | null], Result>("set_led");
export const resetLed = callable<[clientId: string], Result>("reset_led");

export interface InstallInfo {
  tag: string;
  running: boolean;
  error: string | null;
  started: number;
  finished: number | null;
  log_file: string;
  log: string[];
}

export interface DriverStatus {
  kernel: string;
  steamos: boolean;
  dkms_available: boolean;
  installed_version: string | null;
  stale_versions: string[];
  loaded_version: string | null;
  // modules from before the last install are still running
  restart_needed: boolean;
  firmware: boolean;
  latest: string | null;
  install: InstallInfo | null;
}

export const getDriverStatus = callable<[], DriverStatus>("get_driver_status");
export const checkForUpdates = callable<[], DriverStatus>("check_for_updates");
export const startInstall = callable<[tag: string | null], Result>("start_install");
