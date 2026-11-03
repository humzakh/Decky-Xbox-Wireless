import { ButtonItem, Field, Focusable, IconsModule, findClassModule } from "@decky/ui";
import { useEffect, useRef, useState } from "react";
import { Client, reportError, setPairing } from "./backend";
import { ControllerSubPage, navigateControllerSettings } from "./ControllerSubPage";
import { DeviceIcon } from "./DeviceIcon";
import { usePairingCountdown } from "./usePairingCountdown";
import { useXoneState } from "./useXoneState";

export const XBOX_PAIR_ROUTE = "/settings/controller/xboxpair/:controllerIndex";
const TITLE = "Pair an Xbox Controller";

// Steam's Bluetooth pairing page styles
let classes: Record<string, string> | undefined;
function pairingClasses() {
  classes ??= (findClassModule((m) => m.PairingPageContainer && m.SearchingRow && m.ImgWithText) as any) ?? {};
  return classes!;
}

let rowClasses: Record<string, string> | undefined;
// Steam's connected-controller row label, with what it's connected through on the right
const labelClasses = () => (rowClasses ??= (findClassModule((m) => m.ControllerLabel && m.Dongle) as any) ?? {});

/** The row added to "Add a new controller", under Steam's Bluetooth one, while an adapter is plugged in. */
export function XboxPairRow() {
  const state = useXoneState();
  if (!state?.dongles.length) return null;
  const c = labelClasses();
  return (
    <ButtonItem
      label={
        <div className={c.ControllerLabel}>
          <div className={c.Text}>{TITLE}</div>
          <div className={c.Dongle}>{state.dongles[0].model}</div>
        </div>
      }
      layout="inline"
      onClick={() => navigateControllerSettings(XBOX_PAIR_ROUTE)}
    >
      Pair
    </ButtonItem>
  );
}

function XboxPairContent() {
  const state = useXoneState();
  const remaining = usePairingCountdown(state);
  const c = pairingClasses();
  // controllers already connected when the page opened, so newly paired ones stand out
  const known = useRef<Set<string> | null>(null);
  const [paired, setPaired] = useState<Client | null>(null);
  // only offer to pair again once pairing has actually been on, not while it's starting
  const [sawPairing, setSawPairing] = useState(false);
  const dongles = state?.dongles ?? [];
  const pairing = dongles.find((d) => d.pairing);
  useEffect(() => {
    if (pairing) setSawPairing(true);
  }, [!!pairing]);

  const startPairing = () => {
    setPaired(null);
    for (const d of dongles) if (!d.pairing) setPairing(d.id, true).then(reportError);
  };

  // like Steam's Bluetooth page searching as soon as it opens; stop when leaving
  const started = useRef(false);
  const latest = useRef(dongles);
  latest.current = dongles;
  useEffect(() => {
    if (!state || started.current) return;
    started.current = true;
    startPairing();
  }, [state]);
  useEffect(
    () => () => {
      for (const d of latest.current) if (d.pairing) setPairing(d.id, false);
    },
    [],
  );

  useEffect(() => {
    if (!state) return;
    const clients = dongles.flatMap((d) => d.devices.filter((dev) => !dev.connecting && !dev.partial).map((dev) => dev.clients[0]));
    if (!known.current) {
      known.current = new Set(clients.map((cl) => cl.id));
      return;
    }
    const added = clients.find((cl) => !known.current!.has(cl.id));
    if (added) {
      known.current.add(added.id);
      setPaired(added);
    }
  }, [state]);

  if (state && dongles.length === 0) {
    return <Field label="No Xbox Wireless Adapter found" description="Plug one in to pair Xbox controllers." />;
  }

  return (
    <Focusable className={c.PairingPageContainer}>
      {pairing && !paired && (
        <div className={c.SearchingRow}>
          <span>Searching for Xbox controllers… {remaining(pairing)}s</span>
          {IconsModule?.Spinner && <IconsModule.Spinner />}
        </div>
      )}
      {paired && <Field label={paired.name} description="Connected" icon={<DeviceIcon client={paired} />} />}
      {!pairing && (sawPairing || paired) && (
        <ButtonItem label={paired ? "Pair another controller" : "Pairing mode ended"} layout="inline" onClick={startPairing}>
          Pair again
        </ButtonItem>
      )}
      <div className={c.ImgWithText}>
        <div className={c.ModalControllerContainer}>
          {IconsModule?.Arrow && <IconsModule.Arrow direction="down" className={`${c.Arrow} ${c.Xbox}`} />}
          {IconsModule?.XboxOneControllerFrontOutline && (
            <IconsModule.XboxOneControllerFrontOutline className={c.AutoHeightController} highlightGuide />
          )}
        </div>
        <div className={c.Explainer}>
          Hold the pair button on the top of your controller until the Xbox button flashes quickly. It stays lit once
          the controller is paired with the adapter.
        </div>
      </div>
    </Focusable>
  );
}

export function XboxPairPage() {
  return (
    <ControllerSubPage title={TITLE}>
      <XboxPairContent />
    </ControllerSubPage>
  );
}
