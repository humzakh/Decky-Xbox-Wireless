import { ButtonItem, Field, PanelSection, PanelSectionRow, ToggleField } from "@decky/ui";
import { useState } from "react";
import {
  FaBatteryEmpty,
  FaBatteryFull,
  FaBatteryHalf,
  FaBatteryQuarter,
  FaBatteryThreeQuarters,
  FaPlug,
  FaXbox,
} from "react-icons/fa";
import { Client, Device, Dongle, STUCK_FIX, STUCK_TITLE, powerOff, reportError, setPairing } from "./backend";
import { batteryText } from "./battery";
import { DeviceIcon } from "./DeviceIcon";
import { ChatMixToggle } from "./ChatMixToggle";
import { LedSlider } from "./LedSlider";

function BatteryIcon({ client }: { client: Client }) {
  const battery = client.battery;
  if (!battery) return null;
  if (battery.no_battery) return <FaPlug />;
  switch (battery.level) {
    case "Full":
      return <FaBatteryFull />;
    case "High":
      return <FaBatteryThreeQuarters />;
    case "Normal":
      return <FaBatteryHalf />;
    case "Low":
      return <FaBatteryQuarter style={{ color: "#e5484d" }} />;
    default:
      return <FaBatteryEmpty style={{ opacity: 0.5 }} />;
  }
}

const EXPANDED_GROUP_CLASS = "xbox-wireless-expanded";
// Steam's slider has min-width: 270px on the box around SliderControlPanelGroup,
// wider than the panel once indented; let it shrink inside our group only.
const EXPANDED_GROUP_CSS = `.${EXPANDED_GROUP_CLASS} div:has(> div > .SliderControlPanelGroup) { min-width: 0 !important; }`;
const EXPANDED_GROUP = { paddingLeft: "9px" } as const;

// keeps icons vertically centred with the text beside them
const INLINE_ICON = { display: "inline-flex", alignItems: "center", gap: "0.35em" } as const;

export function DeviceRow({ device, dongleId }: { device: Device; dongleId?: string }) {
  const [expanded, setExpanded] = useState(false);

  if (device.connecting) {
    return (
      <PanelSectionRow>
        <Field label="Connecting…" icon={<FaXbox />} description={device.adapter} />
      </PanelSectionRow>
    );
  }

  const [main, ...rest] = device.clients;
  const attachments = rest.filter((c) => !c.phantom);
  const canPowerOff = dongleId !== undefined && device.slot !== null;
  const expandable = canPowerOff || !!main.led || main.chat_mix !== null;
  const description = (
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: "8px" }}>
      <span style={INLINE_ICON}>
        <BatteryIcon client={main} />
        {batteryText(main)}
      </span>
      {attachments.length > 0 && (
        <span style={{ ...INLINE_ICON, gap: "0.8em" }}>
          {attachments.map((a) => (
            <span key={a.id} style={INLINE_ICON}>
              <DeviceIcon client={a} />
              {[a.name, batteryText(a)].filter(Boolean).join(": ")}
            </span>
          ))}
        </span>
      )}
    </div>
  );

  return (
    <>
      <PanelSectionRow>
        <Field
          label={main.name}
          description={description}
          icon={<DeviceIcon client={main} />}
          focusable={expandable}
          highlightOnFocus={expandable}
          onActivate={() => setExpanded(!expanded)}
          onClick={() => setExpanded(!expanded)}
        />
      </PanelSectionRow>
      {expanded && (
        <div className={EXPANDED_GROUP_CLASS} style={EXPANDED_GROUP}>
          <style>{EXPANDED_GROUP_CSS}</style>
          {main.led && (
            <PanelSectionRow>
              <LedSlider client={main} />
            </PanelSectionRow>
          )}
          {main.chat_mix !== null && (
            <PanelSectionRow>
              <ChatMixToggle dial={main.chat_mix} />
            </PanelSectionRow>
          )}
          {canPowerOff && (
            <PanelSectionRow>
              <ButtonItem
                layout="below"
                onClick={async () => {
                  reportError(await powerOff(dongleId!, device.slot!));
                  setExpanded(false);
                }}
              >
                {main.kind === "headset" ? "Turn off headset" : "Turn off controller"}
              </ButtonItem>
            </PanelSectionRow>
          )}
        </div>
      )}
    </>
  );
}

/** An adapter's devices. */
export function DongleDevices({ dongle }: { dongle: Dongle }) {
  // a stuck adapter's slots would each show as "Connecting…"
  const devices = dongle.devices.filter((d) => !d.partial && !(dongle.stuck && d.connecting));
  return (
    <>
      {dongle.stuck && (
        <PanelSectionRow>
          <Field label={STUCK_TITLE} description={STUCK_FIX} />
        </PanelSectionRow>
      )}
      {devices.length === 0 && !dongle.stuck && (
        <PanelSectionRow>
          <Field label="No controllers connected" />
        </PanelSectionRow>
      )}
      {devices.map((device) => (
        <DeviceRow key={device.adapter} device={device} dongleId={dongle.id} />
      ))}
    </>
  );
}

function PairingToggle({ dongle, remaining }: { dongle: Dongle; remaining: number }) {
  const [busy, setBusy] = useState(false);
  return (
    <PanelSectionRow>
      <ToggleField
        label="Pairing mode"
        description={
          dongle.pairing
            ? `Hold the pair button on your controller until the Xbox button flashes quickly · ${remaining}s`
            : `Enable for ${remaining} seconds`
        }
        checked={dongle.pairing}
        disabled={busy}
        onChange={async (enabled) => {
          setBusy(true);
          reportError(await setPairing(dongle.id, enabled));
          setBusy(false);
        }}
      />
    </PanelSectionRow>
  );
}

export function DongleSection({ dongle, title, remaining }: { dongle: Dongle; title: string; remaining: number }) {
  return (
    <PanelSection title={title}>
      <DongleDevices dongle={dongle} />
      <PairingToggle dongle={dongle} remaining={remaining} />
    </PanelSection>
  );
}
