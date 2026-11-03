import { ButtonItem, DialogButton, Field, Focusable, IconsModule, Router, findClassModule } from "@decky/ui";
import { useEffect } from "react";
import { FaXbox } from "react-icons/fa";
import { Dongle, STUCK_FIX, STUCK_TITLE, forgetDevice, powerOff, reportError } from "./backend";
import { CONTROLLER_MENU_ROUTE, ControllerSubPage, navigateControllerSettings } from "./ControllerSubPage";
import { DriverSettingsRows } from "./DriverSection";
import { XBOX_ONE_CONTROLLER } from "./HeaderBatteries";
import { HeadsetIcon } from "./HeadsetIcon";
import { useXoneState } from "./useXoneState";

export const XBOX_ADAPTER_PREFIX = "/settings/controller/xboxadapter/";

const adapterRoute = (dongle: Dongle) => XBOX_ADAPTER_PREFIX + encodeURIComponent(dongle.id);

function summary(dongle: Dongle) {
  if (dongle.stuck) return STUCK_TITLE;
  const connected = dongle.devices.filter((d) => !d.connecting && !d.partial).length;
  return connected === 1 ? "1 device connected" : `${connected} devices connected`;
}

/** The "Xbox Controller Adapters" section of the Controller page: adapters, then the driver. */
export function XboxAdaptersRows() {
  const state = useXoneState();
  return (
    <>
      {state && state.dongles.length === 0 && (
        <Field label="No adapter found" description="Plug in an Xbox Wireless Adapter." icon={<FaXbox />} />
      )}
      {state?.dongles.map((dongle) => (
        <ButtonItem
          key={dongle.id}
          label={dongle.model}
          description={summary(dongle)}
          icon={<FaXbox />}
          layout="inline"
          onClick={() => navigateControllerSettings(adapterRoute(dongle))}
        >
          Details
        </ButtonItem>
      ))}
      <DriverSettingsRows />
    </>
  );
}

let slotClasses: Record<string, string> | undefined;
// Steam's adapter page rows
const classes = () => (slotClasses ??= (findClassModule((m) => m.PairingSlot && m.PeerSerialNumber) as any) ?? {});
const localize = (token: string, fallback: string): string =>
  (window as any).LocalizationManager?.LocalizeString?.(token) || fallback;
// controllers the adapter connects at a time, shown as slots like Steam shows its adapter's four
const ADAPTER_SLOTS = 8;

/** One row like a pairing slot on Steam's adapter page: status, device, serial and a button. */
function DeviceSlot(props: {
  index: number;
  status: string;
  active: boolean;
  // an empty slot, like Steam's unpaired ones
  empty?: boolean;
  name: string;
  headset: boolean;
  serial: string | null;
  action: string;
  onAction?: () => void;
  autoFocus?: boolean;
}) {
  const c = classes();
  const connection = [c.Connection, props.active && c.Active, props.empty && c.Unpaired];
  return (
    <Focusable className={c.PairingSlot}>
      <div className={c.Label}>{props.index}</div>
      <div className={connection.filter(Boolean).join(" ")}>{props.status}</div>
      <div className={c.PeerDevice}>
        <div className={c.PeerIcon}>
          {props.empty ? null : props.headset ? (
            // square like Steam's controller icon; the row would squeeze its width otherwise
            <HeadsetIcon className={c.Icon} style={{ width: "auto", aspectRatio: "1", flexShrink: 0 }} />
          ) : (
            IconsModule?.ControllerType && <IconsModule.ControllerType className={c.Icon} controllerType={XBOX_ONE_CONTROLLER} />
          )}
        </div>
        <div className={c.PeerName}>{props.name}</div>
      </div>
      <div className={c.PeerSerialNumber}>{props.serial}</div>
      <DialogButton
        className={c.Forget}
        // Steam's button takes it; @decky/ui's types leave it out
        {...({ autoFocus: props.autoFocus } as any)}
        focusable={!!props.onAction}
        disabled={!props.onAction}
        onClick={props.onAction}
      >
        {props.action}
      </DialogButton>
    </Focusable>
  );
}

/** Connected devices, then ones that connected before, as Steam lists its adapter's slots. */
function AdapterDevices({ dongle }: { dongle: Dongle }) {
  // a stuck adapter's slots would each show as connecting
  const connected = dongle.devices.filter((d) => !d.partial && !(dongle.stuck && d.connecting));
  const forget = localize("#Settings_Controller_PairingInfo_Forget", "Forget");
  const slots = [
    ...connected.map((device) => {
      const main = device.clients[0];
      const canTurnOff = !device.connecting && device.slot !== null;
      return {
        key: device.adapter,
        status: device.connecting ? "Connecting…" : localize("#Settings_Controller_PairingInfo_Active", "Active"),
        active: !device.connecting,
        name: main?.name ?? "",
        headset: main?.kind === "headset",
        serial: main?.serial ?? null,
        action: "Turn Off",
        onAction: canTurnOff ? () => powerOff(dongle.id, device.slot!).then(reportError) : undefined,
      };
    }),
    ...(dongle.disconnected ?? []).map((known) => ({
      key: known.key,
      status: localize("#Settings_Controller_PairingInfo_Disconnected", "Disconnected"),
      active: false,
      name: known.name,
      headset: known.kind === "headset",
      serial: known.key.startsWith("serial:") ? known.key.slice("serial:".length) : null,
      action: forget,
      onAction: () => forgetDevice(dongle.id, known.key).then(reportError),
    })),
  ];
  for (let i = slots.length; i < ADAPTER_SLOTS; i++) {
    slots.push({
      key: `empty-${i}`,
      status: localize("#Settings_Controller_PairingInfo_Unpaired", "Unpaired"),
      active: false,
      empty: true,
      name: "",
      headset: false,
      serial: null,
      action: "Turn Off",
      onAction: undefined,
    } as (typeof slots)[number]);
  }
  const focusAt = slots.findIndex((s) => s.onAction);
  return (
    <>
      {dongle.stuck && <Field label={STUCK_TITLE} description={STUCK_FIX} />}
      {slots.map(({ key, ...slot }, i) => (
        <DeviceSlot key={key} index={i + 1} autoFocus={i === focusAt} {...slot} />
      ))}
    </>
  );
}

/** An adapter's details, like Steam's page for its own adapter. */
export function XboxAdapterPage() {
  const state = useXoneState();
  const path = Router.WindowStore?.GamepadUIMainWindowInstance?.m_locationPathname ?? "";
  const id = decodeURIComponent(path.slice(XBOX_ADAPTER_PREFIX.length));
  const dongle = state?.dongles.find((d) => d.id === id);

  // like Steam's adapter page, go back once the adapter is unplugged
  useEffect(() => {
    if (state && !dongle) navigateControllerSettings(CONTROLLER_MENU_ROUTE);
  }, [state, dongle]);

  return (
    <ControllerSubPage title={dongle?.model ?? "Xbox Wireless Adapter"}>
      {dongle && (
        <>
          <Field
            label={dongle.model}
            description="Connects up to 8 Xbox controllers at a time"
            icon={<FaXbox />}
            bottomSeparator="standard"
          />
          <AdapterDevices dongle={dongle} />
        </>
      )}
    </ControllerSubPage>
  );
}
