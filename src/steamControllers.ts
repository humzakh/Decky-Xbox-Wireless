import { Client, State } from "./backend";

export type XoneController = { dongleId: string; slot: number; client: Client };

/** Steam's controller store; its list entries are Steam's view of each connected controller. */
export function steamControllerStore(): any {
  return (window as any).ControllerStore;
}

/**
 * Pairs Steam's controllers (by nControllerIndex) with xone's wireless devices by USB ids.
 * Steam's serial for them is an opaque hash, so identical models are paired up in connection order.
 */
export function matchControllers(state: State, controllers: any[]) {
  const byModel = new Map<string, XoneController[]>();
  for (const dongle of state.dongles) {
    const devices = dongle.devices
      .filter((d) => !d.connecting && !d.partial && d.slot !== null)
      .sort((a, b) => a.slot! - b.slot!);
    for (const device of devices) {
      const client = device.clients[0];
      if (!client.vendor_id || !client.product_id) continue;
      const key = `${parseInt(client.vendor_id, 16)}:${parseInt(client.product_id, 16)}`;
      byModel.set(key, [...(byModel.get(key) ?? []), { dongleId: dongle.id, slot: device.slot!, client }]);
    }
  }
  const matches = new Map<number, XoneController>();
  for (const c of [...controllers].sort((a, b) => a.nControllerIndex - b.nControllerIndex)) {
    const match = byModel.get(`${c.unVendorID}:${c.unProductID}`)?.shift();
    if (match) matches.set(c.nControllerIndex, match);
  }
  return matches;
}

/** Steam's controller index for an xone client, if Steam has it. */
export function steamIndexOf(state: State, clientId: string) {
  const controllers = steamControllerStore()?.GetControllers?.() ?? [];
  for (const [index, match] of matchControllers(state, controllers)) {
    if (match.client.id === clientId) return index;
  }
  return undefined;
}
