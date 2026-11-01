import { addEventListener, removeEventListener, toaster } from "@decky/api";
import { State, getState, powerOff } from "./backend";
import { XoneController, matchControllers, steamControllerStore } from "./steamControllers";

/**
 * Adds "Turn off controller" to the menu Steam opens on a held Xbox button. Steam only offers
 * it for controllers it knows are wireless, and it sees xone's as wired, so we mark them
 * wireless in its controller store and turn them off through xone when it's picked.
 * If Steam moves any of these, nothing changes.
 */
export function addSteamPowerOff() {
  const store = steamControllerStore();
  const input = (window as any).SteamClient?.Input;
  if (typeof store?.DoControllerListQuery !== "function" || typeof input?.TurnOffController !== "function") {
    console.warn("[Xbox Wireless] couldn't find Steam's controller store");
    return () => {};
  }

  let state: State | null = null;
  let targets = new Map<number, XoneController>();
  // controllers we flipped to wireless, to flip back on unload
  const marked = new Set<number>();

  const apply = () => {
    const controllers: any[] = store.GetControllers() ?? [];
    targets = state ? matchControllers(state, controllers) : new Map();
    for (const c of controllers) {
      if (targets.has(c.nControllerIndex) && !c.bWireless) {
        c.bWireless = true;
        marked.add(c.nControllerIndex);
      }
    }
  };

  const onState = (s: State) => {
    state = s;
    apply();
  };
  const listener = addEventListener<[State]>("state", onState);
  let active = true;
  getState().then((s) => active && onState(s));

  // Steam replaces its controller list on every change, losing our flag
  const query = store.DoControllerListQuery;
  store.DoControllerListQuery = async function (this: unknown, ...args: unknown[]) {
    const ret = await query.apply(this, args);
    if (active) apply();
    return ret;
  };

  const turnOff = input.TurnOffController;
  input.TurnOffController = (index: number, ...rest: unknown[]) => {
    const target = targets.get(index);
    if (!target) return turnOff.call(input, index, ...rest);
    powerOff(target.dongleId, target.slot).then((res) => {
      if (!res.ok) toaster.toast({ title: "Xbox Wireless", body: res.error ?? "Couldn't turn off the controller" });
    });
  };

  return () => {
    active = false;
    removeEventListener("state", listener);
    input.TurnOffController = turnOff;
    delete store.DoControllerListQuery;
    for (const c of store.GetControllers() ?? []) {
      if (marked.has(c.nControllerIndex)) c.bWireless = false;
    }
  };
}
