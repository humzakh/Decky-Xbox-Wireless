import { Field, IconsModule, findClassModule } from "@decky/ui";
import { ReactElement, ReactNode } from "react";
import { CRITICAL_LEVEL, acState, batteryFraction, batteryText } from "./battery";
import { onControllerPage } from "./ControllerSubPage";
import { LedSlider } from "./LedSlider";
import { patchSettingsPage } from "./SettingsPatch";
import { SilentBoundary } from "./SilentBoundary";
import { XBOX_ADAPTER_PREFIX, XboxAdapterPage, XboxAdaptersRows } from "./XboxAdapters";
import { XBOX_PAIR_ROUTE, XboxPairPage, XboxPairRow } from "./XboxPairPage";
import { matchControllers, steamControllerStore } from "./steamControllers";
import { useXoneState } from "./useXoneState";

const CONTROLLER_ROUTE = "/settings/controller/";
const XBOX_PAIR_PREFIX = XBOX_PAIR_ROUTE.slice(0, XBOX_PAIR_ROUTE.lastIndexOf("/"));

type FC = (props: any) => ReactNode;

/** Recognises a function component by its code, caching the answer per function. */
function codeMatcher(...needles: string[]) {
  const seen = new WeakMap<FC, boolean>();
  return (f: FC) => {
    let hit = seen.get(f);
    if (hit === undefined) {
      const src = f.toString();
      hit = needles.every((n) => src.includes(n));
      seen.set(f, hit);
    }
    return hit;
  };
}

// None of these are exported: the page that switches on the route's type (menu, controller, pair, ...)
const isTypeSwitch = codeMatcher('case"controller"', 'case"btpair"');
// the page for one controller, the only one linking to its input test and calibration
const isControllerPage = codeMatcher("ControllerDeviceTestInput", "ControllerDeviceCalibration");
// its connection and battery rows, which Steam only fills in for its own controllers
const isConnectionRow = codeMatcher("#Settings_Controller_Connection_USB", "#Settings_Controller_Connection_BT");
const isBatteryRow = codeMatcher("#Settings_Controller_Battery", "ucBatteryLevel");
// the main Controller page listing connected controllers
const isMenuPage = codeMatcher("#Settings_Controller_ConnectedHeader", "#Settings_Controller_AddANewController_Button");
// "Add a new controller" (the main page's row for it has this title too, so check that first)
const isAddPage = codeMatcher("#Settings_Controller_AddANewController");
// and a connected controller's row on the main page, linking to its page
const isControllerRow = codeMatcher("#Settings_Controller_Details", '"Controller","controller"');

let rowClasses: Record<string, string> | undefined;
// Steam's connected-controller row label: icon, name and what it's connected through
const labelClasses = () => (rowClasses ??= (findClassModule((m) => m.ControllerLabel && m.Dongle) as any) ?? {});

/** Says xone's controllers are on the Xbox adapter, where Steam shows nothing (or USB). */
function ConnectedThrough({ controllerIndex, steam }: { controllerIndex: number; steam: ReactNode }) {
  const match = useXoneController(controllerIndex);
  if (!match) return <>{steam}</>;
  return <div className={labelClasses().Dongle}>{match.dongle?.model ?? "Xbox Wireless Adapter"}</div>;
}

/** xone's client and adapter for the controller at Steam's `controllerIndex`, if it's one of ours. */
function useXoneController(controllerIndex: number) {
  const state = useXoneState();
  const controllers = steamControllerStore()?.GetControllers?.() ?? [];
  const match = state ? matchControllers(state, controllers).get(controllerIndex) : undefined;
  return match && { client: match.client, dongle: state!.dongles.find((d) => d.id === match.dongleId) };
}

const useXoneClient = (controllerIndex: number) => useXoneController(controllerIndex)?.client;

/** Like Steam's connection row for its own controllers. */
function ControllerConnection({ controllerIndex }: { controllerIndex: number }) {
  const match = useXoneController(controllerIndex);
  return match ? <Field label="Connection">{match.dongle?.model ?? "Xbox Wireless Adapter"}</Field> : null;
}

function ControllerLed({ controllerIndex }: { controllerIndex: number }) {
  const client = useXoneClient(controllerIndex);
  return client?.led ? <LedSlider client={client} /> : null;
}

/** Like Steam's battery row for its own controllers, with xone's level instead of a percentage. */
function ControllerBattery({ controllerIndex }: { controllerIndex: number }) {
  const client = useXoneClient(controllerIndex);
  if (!client?.battery) return null;
  const level = batteryFraction(client);
  const c = labelClasses();
  return (
    <Field label="Battery">
      <div className={c.BatteryLevel}>
        <div>{batteryText(client)}</div>
        {level !== null && IconsModule?.Battery && (
          <IconsModule.Battery
            className={c.BatteryIcon}
            batteryCriticalThreshold={CRITICAL_LEVEL}
            uniformSizing
            acState={acState(client)}
            batteryLevel={level}
          />
        )}
      </div>
    </Field>
  );
}

/** Returns `el` with function component types below it swapped where `swap` gives a new one. */
function swapTypes(el: any, swap: (f: FC) => FC | undefined): any {
  if (!el || typeof el !== "object") return el;
  if (Array.isArray(el)) {
    const out = el.map((c) => swapTypes(c, swap));
    return out.some((c, i) => c !== el[i]) ? out : el;
  }
  if (typeof el.type === "function" && !el.type.prototype?.isReactComponent) {
    const type = swap(el.type);
    if (type) return { ...el, type };
  }
  const children = el.props?.children;
  const swapped = swapTypes(children, swap);
  return swapped === children ? el : { ...el, props: { ...el.props, children: swapped } };
}

const withChildren = (el: any, children: any[]) => ({ ...el, props: { ...el.props, children } });

/**
 * Additions to Steam's Settings > Controller pages:
 * - a controller's connection and battery on its page, as Steam shows its own controllers', and the LED
 *   brightness slider at the end of that page's first section
 * - "Pair an Xbox Controller" on "Add a new controller", opening our own pairing sub-page
 * - an "Xbox Controller Adapters" section on the main Controller page, under Steam's adapters:
 *   each adapter with a details sub-page of its devices, then the xone driver
 * - "Xbox Wireless Adapter" as what xone's controllers are connected through, in that page's list
 * The Controller page renders its sub-pages directly, so we wrap it, the type switch inside it
 * and the sub-pages in turn. If Steam moves any of these, the pages render untouched.
 */
export function addControllerSettings() {
  const wrappers = new WeakMap<FC, FC>();
  // stable wrapper per original component, so React doesn't remount it every render
  const wrap = (original: FC, edit: (ret: any, props: any) => any): FC => {
    let w = wrappers.get(original);
    if (!w) {
      w = (props: any) => edit(original(props), props);
      wrappers.set(original, w);
    }
    return w;
  };
  // connection and battery where Steam's own rows go, and the LED at the end of the first section
  const addToControllerPage = (ret: any) => {
    let children = ret?.props?.children;
    if (!Array.isArray(children)) return ret;
    const index = children.find((c: any) => typeof c?.props?.controllerIndex === "number")?.props.controllerIndex;
    if (index === undefined) return ret;
    const insert = (at: number, el: ReactNode) => [...children.slice(0, at), el, ...children.slice(at)];

    const after = (isSteamRow: (f: FC) => boolean, key: string, row: ReactNode) => {
      const at = children.findIndex((c: any) => typeof c?.type === "function" && isSteamRow(c.type));
      if (at >= 0) children = insert(at + 1, <SilentBoundary key={key} name={key}>{row}</SilentBoundary>);
    };
    after(isConnectionRow, "xbox-wireless-connection", <ControllerConnection controllerIndex={index} />);
    after(isBatteryRow, "xbox-wireless-battery", <ControllerBattery controllerIndex={index} />);
    // the first section is the rows above the first labelled group
    const groupAt = children.findIndex((c: any) => c?.props?.label != null && Array.isArray(c?.props?.children));
    if (groupAt >= 0) {
      children = insert(groupAt, (
        <SilentBoundary key="xbox-wireless-led" name="controller page LED">
          <ControllerLed controllerIndex={index} />
        </SilentBoundary>
      ));
    }
    return withChildren(ret, children);
  };

  // <Page>[<Header>[<Back/>, title]</Header>, <Focusable>[...options, <BluetoothRow/>]</Focusable>]</Page>
  const addXboxRow = (ret: any) => {
    const [header, body] = Array.isArray(ret?.props?.children) ? ret.props.children : [];
    if (!Array.isArray(header?.props?.children) || !Array.isArray(body?.props?.children)) return ret;
    const row = (
      <SilentBoundary key="xbox-wireless-pair" name="Xbox pairing row">
        <XboxPairRow />
      </SilentBoundary>
    );
    return withChildren(ret, [header, withChildren(body, [...body.props.children, row])]);
  };

  // <Row label={<div>[<Icon/>, <div>{name}</div>, connection && <div>{connection}</div>]</div>}/>
  const addConnection = (ret: any, props: any) => {
    const label = ret?.props?.label;
    const parts = label?.props?.children;
    const index = props?.details?.nControllerIndex;
    if (!Array.isArray(parts) || parts.length < 2 || typeof index !== "number") return ret;
    const connection = <ConnectedThrough key="connection" controllerIndex={index} steam={parts[2]} />;
    return { ...ret, props: { ...ret.props, label: withChildren(label, [parts[0], parts[1], connection]) } };
  };

  // A section like Steam's own, copied from its last labelled one ("Advanced Settings") and put
  // before it, which is right under "Steam Controller Adapters" when that's shown.
  const addAdapters = (ret: any) => {
    const children = ret?.props?.children;
    if (!Array.isArray(children)) return ret;
    const isSection = (c: any) => c?.props?.label != null && c?.props?.children != null;
    const lastAt = children.length - 1 - [...children].reverse().findIndex(isSection);
    if (lastAt >= children.length) return ret;
    const section = children[lastAt];
    const adapters = {
      ...section,
      key: "xbox-wireless-adapters",
      props: {
        ...section.props,
        label: "Xbox Controller Adapters",
        children: (
          <SilentBoundary name="adapters section">
            <XboxAdaptersRows />
          </SilentBoundary>
        ),
      },
    };
    return withChildren(ret, [...children.slice(0, lastAt), adapters, ...children.slice(lastAt)]);
  };

  const inMenuPage = (ret: any) =>
    swapTypes(addAdapters(ret), (f) => (isControllerRow(f) ? wrap(f, addConnection) : undefined));

  // Steam doesn't know our sub-pages and falls back to its menu; show ours instead
  const ourPage = () => {
    if (onControllerPage(XBOX_PAIR_PREFIX)) return <XboxPairPage />;
    if (onControllerPage(XBOX_ADAPTER_PREFIX)) return <XboxAdapterPage />;
    return null;
  };

  const inTypeSwitch = (ret: any) => {
    const page = ourPage();
    if (page) return <SilentBoundary name="Xbox controller settings page">{page}</SilentBoundary>;
    return swapTypes(ret, (f) => {
      if (isControllerPage(f)) return wrap(f, addToControllerPage);
      if (isMenuPage(f)) return wrap(f, inMenuPage);
      if (isAddPage(f)) return wrap(f, addXboxRow);
      return undefined;
    });
  };
  const inPage = (ret: any) => swapTypes(ret, (f) => (isTypeSwitch(f) ? wrap(f, inTypeSwitch) : undefined));

  return patchSettingsPage(CONTROLLER_ROUTE, (content: ReactElement) =>
    typeof content.type === "function" ? { ...content, type: wrap(content.type as FC, inPage) } : content,
  );
}
