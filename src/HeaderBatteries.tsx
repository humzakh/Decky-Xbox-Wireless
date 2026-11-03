import { Focusable, IconsModule, Navigation, Router, findClassModule, findModuleExport, findSP } from "@decky/ui";
import { Client } from "./backend";
import { CRITICAL_LEVEL, acState, batteryFraction } from "./battery";
import { HeadsetIcon } from "./HeadsetIcon";
import { SilentBoundary } from "./SilentBoundary";
import { steamIndexOf } from "./steamControllers";
import { useXoneState } from "./useXoneState";

// Steam's EControllerType; all Xbox types draw the same icon
export const XBOX_ONE_CONTROLLER = 32;
function DeviceBattery({ client, classes, onActivate }: {
  client: Client;
  classes: Record<string, string>;
  onActivate: () => void;
}) {
  const level = batteryFraction(client);
  if (level === null) return null;
  const headset = client.kind === "headset";

  // mirrors the markup of Steam's own header controller battery
  return (
    <Focusable
      noFocusRing
      role="link"
      aria-label={client.name}
      onOKActionDescription={headset ? "Audio Settings" : "Controller Details"}
      onActivate={onActivate}
      onClick={onActivate}
      className={`${classes.HeaderItem} ${classes.Clickable}`}
    >
      <div className={classes.ControllerBatteryImgContainer}>
        {headset ? (
          // Steam crops device icons to their left half; mirrored, keep the half with the mic
          <HeadsetIcon className={classes.ControllerImg} style={{ clipPath: "inset(0 0 0 50%)" }} />
        ) : (
          <IconsModule.ControllerType className={classes.ControllerImg} controllerType={XBOX_ONE_CONTROLLER} />
        )}
        <IconsModule.Battery
          acState={acState(client)}
          batteryLevel={level}
          batteryCriticalThreshold={CRITICAL_LEVEL}
          className={`${classes.LowBatteryGauge} ${classes.ControllerBatteryIndicator}`}
        />
      </div>
    </Focusable>
  );
}

/**
 * Opens a Steam Settings page the way Steam's own settings links do: from inside Settings it
 * replaces the current page, so Back still leaves Settings, and pressing again adds nothing.
 */
function openSteamSettings(path: string) {
  const win = Router.WindowStore?.GamepadUIMainWindowInstance;
  if (!win || win.m_locationPathname === path) return;
  const inSettings = !!win.m_locationPathname?.startsWith("/settings");
  win.Navigate(path, inSettings, false, { bDirectNav: !inSettings } as any);
}

function XboxBatteries({ classes }: { classes: Record<string, string> }) {
  const state = useXoneState();

  // Steam's own settings for the device: the controller's page, or Audio for a headset
  const openSettings = (client: Client) => {
    const steamIndex = client.kind === "headset" || !state ? undefined : steamIndexOf(state, client.id);
    if (steamIndex !== undefined) openSteamSettings(`/settings/controller/controller/${steamIndex}`);
    else if (client.kind === "headset") openSteamSettings("/settings/audio");
    Navigation.CloseSideMenus();
  };
  // like Steam, only wireless devices: wired ones are on USB power anyway. Headsets
  // plugged into a controller run off it and have no battery of their own.
  const devices = (state?.dongles ?? [])
    .flatMap((d) => d.devices)
    .filter((d) => !d.connecting && !d.partial)
    .map((d) => d.clients[0])
    .filter((c) => c.battery);

  return (
    <>
      {devices.map((c) => (
        <DeviceBattery key={c.id} client={c} classes={classes} onActivate={() => openSettings(c)} />
      ))}
    </>
  );
}

/** Re-renders mounted header battery rows so a patch applies (or goes away) without waiting. */
function rerenderRows(row: unknown) {
  const header: any = findSP()?.document.getElementById("header");
  const key = header && Object.keys(header).find((k) => k.startsWith("__reactFiber$"));
  if (!key) return;
  const stack = [header[key].child];
  while (stack.length) {
    const fiber = stack.pop();
    if (!fiber) continue;
    if (fiber.type === row) fiber.return?.stateNode?.forceUpdate?.();
    stack.push(fiber.child, fiber.sibling);
  }
}

/**
 * Adds xone controllers and headsets to the controller batteries in Steam's top bar. Steam
 * hides Xbox controllers there since it can't read their battery, so ours go right after its own:
 * each header item is wrapped in Steam's error boundary class, and when that boundary wraps
 * the controller battery row we render our icons after it.
 * If a Steam update moves any of these, the header renders untouched.
 */
export function addHeaderBatteries() {
  let BatteryRow: unknown, Boundary: any, classes: Record<string, string> | void;
  try {
    BatteryRow = findModuleExport(
      (e) => typeof e === "function" && !e.prototype?.isReactComponent && e.toString().includes("DesktopBatteryRow"),
    );
    Boundary = findModuleExport(
      (e) => typeof e === "function" && e.prototype?.componentDidCatch && e.prototype.render?.toString().includes("lastErrorKey"),
    );
    classes = findClassModule((m) => m.ControllerBatteryImgContainer && m.HeaderItem);
  } catch (e) {
    console.warn("[Xbox Wireless] couldn't find Steam's header", e);
    return () => {};
  }
  if (!BatteryRow || !Boundary || !classes || !IconsModule?.Battery || !IconsModule?.ControllerType) {
    console.warn("[Xbox Wireless] couldn't find Steam's header controller batteries");
    return () => {};
  }

  const render = Boundary.prototype.render;
  const extra = (
    <SilentBoundary name="header battery">
      <XboxBatteries classes={classes} />
    </SilentBoundary>
  );
  Boundary.prototype.render = function (this: any) {
    const ret = render.call(this);
    return this.props.children?.type === BatteryRow ? <>{ret}{extra}</> : ret;
  };
  rerenderRows(BatteryRow);

  return () => {
    Boundary.prototype.render = render;
    rerenderRows(BatteryRow);
  };
}
