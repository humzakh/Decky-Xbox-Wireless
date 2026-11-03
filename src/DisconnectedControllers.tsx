import { Field, IconsModule, findClassModule } from "@decky/ui";
import { ComponentType, ReactNode } from "react";
import { XBOX_ONE_CONTROLLER } from "./HeaderBatteries";
import { useXoneState } from "./useXoneState";

let classes: Record<string, string> | undefined;
// Steam's disconnected-controller row label
const rowClasses = () =>
  (classes ??= (findClassModule((m) => m.DisconnectedControllerLabel && m.ControllerLabel) as any) ?? {});

/** Controllers that have connected to a plugged-in adapter before but aren't connected now. */
function useDisconnected() {
  const state = useXoneState();
  return (state?.dongles ?? []).flatMap((dongle) =>
    (dongle.disconnected ?? []).filter((d) => d.kind !== "headset").map((device) => ({ device, dongle })),
  );
}

/** Rows like Steam's for its own disconnected controllers, to go in its section. */
export function DisconnectedRows() {
  const c = rowClasses();
  return (
    <>
      {useDisconnected().map(({ device, dongle }) => (
        <Field
          key={`${dongle.id}/${device.key}`}
          label={
            <div className={c.DisconnectedControllerLabel}>
              {IconsModule?.ControllerType && (
                <IconsModule.ControllerType className={c.Icon} controllerType={XBOX_ONE_CONTROLLER} />
              )}
              <div className={c.Text}>{device.name}</div>
              <div className={c.Dongle}>{dongle.model}</div>
            </div>
          }
        />
      ))}
    </>
  );
}

/** Steam's section, for when it has no disconnected controllers of its own and leaves it out. */
export function DisconnectedSection({ Section, label }: { Section: ComponentType<any>; label: ReactNode }) {
  if (useDisconnected().length === 0) return null;
  return (
    <Section label={label}>
      <DisconnectedRows />
    </Section>
  );
}
