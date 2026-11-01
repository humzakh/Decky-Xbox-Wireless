import { ButtonItem, Field, Router } from "@decky/ui";
import { useEffect } from "react";
import { FaXbox } from "react-icons/fa";
import { Dongle, STUCK_TITLE } from "./backend";
import { CONTROLLER_MENU_ROUTE, ControllerSubPage, navigateControllerSettings } from "./ControllerSubPage";
import { DongleDevices } from "./Devices";
import { DriverSettingsRows } from "./DriverSection";
import { XboxPairRow } from "./XboxPairPage";
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

/** An adapter's details: its devices, like the plugin panel shows them, and a way to pair more. */
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
          <DongleDevices dongle={dongle} />
          <XboxPairRow />
        </>
      )}
    </ControllerSubPage>
  );
}
