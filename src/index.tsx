import { Field, PanelSection, PanelSectionRow, ToggleField, staticClasses } from "@decky/ui";
import { addEventListener, definePlugin, removeEventListener, toaster } from "@decky/api";
import { useEffect, useState } from "react";
import { FaXbox } from "react-icons/fa";
import { Settings, State, getSettings, getState, reportError, setSetting } from "./backend";
import { addControllerSettings } from "./ControllerSettings";
import { DeviceRow, DongleSection } from "./Devices";
import { DriverSection } from "./DriverSection";
import { usePairingCountdown } from "./usePairingCountdown";
import { addHeaderBatteries } from "./HeaderBatteries";
import { addSteamPowerOff } from "./SteamPowerOff";

function NotificationSection({ settings, onSettings }: {
  settings: Settings;
  onSettings: (s: Settings) => void;
}) {
  const toggle = (key: "notify_connect" | "notify_low_battery") => async (value: boolean) => {
    onSettings({ ...settings, [key]: value });
    reportError(await setSetting(key, value));
  };
  return (
    <PanelSection title="Notifications">
      <PanelSectionRow>
        <ToggleField label="Connect / disconnect" checked={settings.notify_connect} onChange={toggle("notify_connect")} />
      </PanelSectionRow>
      <PanelSectionRow>
        <ToggleField label="Low battery" checked={settings.notify_low_battery} onChange={toggle("notify_low_battery")} />
      </PanelSectionRow>
    </PanelSection>
  );
}

function Content() {
  const [state, setState] = useState<State | null>(null);
  const [settings, setSettings] = useState<Settings | null>(null);
  const remaining = usePairingCountdown(state);

  useEffect(() => {
    getState().then(setState);
    getSettings().then(setSettings);
    const listener = addEventListener<[State]>("state", setState);
    return () => removeEventListener("state", listener);
  }, []);

  if (!state || !settings) {
    return (
      <PanelSection>
        <PanelSectionRow>
          <Field label="Loading…" />
        </PanelSectionRow>
      </PanelSection>
    );
  }

  const wired = state.wired.filter((d) => !d.partial);

  if (!state.driver_loaded) {
    return <DriverSection />;
  }

  return (
    <>
      {state.dongles.length === 0 && (
        <PanelSection title="Wireless adapter">
          <PanelSectionRow>
            <Field label="No adapter found" description="Plug in an Xbox Wireless Adapter." />
          </PanelSectionRow>
        </PanelSection>
      )}
      {state.dongles.map((dongle, i) => (
        <DongleSection
          key={dongle.id}
          dongle={dongle}
          title={state.dongles.length > 1 ? `${dongle.model} ${i + 1}` : dongle.model}
          remaining={remaining(dongle)}
        />
      ))}
      {wired.length > 0 && (
        <PanelSection title="Wired">
          {wired.map((device) => (
            <DeviceRow key={device.adapter} device={device} />
          ))}
        </PanelSection>
      )}
      <NotificationSection settings={settings} onSettings={setSettings} />
      <DriverSection />
    </>
  );
}

export default definePlugin(() => {
  const notify = addEventListener<[title: string, body: string]>("notify", (title, body) => {
    toaster.toast({ title, body, icon: <FaXbox /> });
  });
  const removeHeaderBatteries = addHeaderBatteries();
  const removeSteamPowerOff = addSteamPowerOff();
  const removeControllerSettings = addControllerSettings();

  return {
    name: "Xbox Wireless",
    titleView: <div className={staticClasses.Title}>Xbox Wireless</div>,
    content: <Content />,
    icon: <FaXbox />,
    onDismount() {
      removeEventListener("notify", notify);
      removeHeaderBatteries();
      removeSteamPowerOff();
      removeControllerSettings();
    },
  };
});
