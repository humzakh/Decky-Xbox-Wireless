import { DialogButton, DialogHeader, Focusable, IconsModule, Router, findClassModule } from "@decky/ui";
import { ReactNode } from "react";

export const CONTROLLER_MENU_ROUTE = "/settings/controller/menu/:controllerIndex";

/** Moves between Controller settings pages the way Steam does, replacing the current one. */
export function navigateControllerSettings(path: string) {
  Router.WindowStore?.GamepadUIMainWindowInstance?.Navigate(path, true, false, { bDirectNav: false } as any);
}

/** True while the main window shows the page at `prefix` (a route without its last segment). */
export function onControllerPage(prefix: string) {
  return !!Router.WindowStore?.GamepadUIMainWindowInstance?.m_locationPathname?.startsWith(prefix);
}

let classes: { header?: string; back?: Record<string, string> } | undefined;
function pageClasses() {
  classes ??= {
    header: (findClassModule((m) => m.ControllerSettingsHeader && m.DongleLabel) as any)?.ControllerSettingsHeader,
    back: (findClassModule((m) => m.BackButton && m.BackButtonContent) as any) ?? {},
  };
  return classes;
}

const back = () => navigateControllerSettings(CONTROLLER_MENU_ROUTE);

/**
 * A sub-page of Settings > Controller, like Steam's own "Add a new controller": a header with a
 * back button to the Controller page, which B also goes back to.
 */
export function ControllerSubPage({ title, children }: { title: ReactNode; children: ReactNode }) {
  const { header, back: b } = pageClasses();
  return (
    <Focusable onCancelButton={back}>
      <DialogHeader className={header}>
        <DialogButton onClick={back} className={b?.BackButton}>
          <div className={b?.BackButtonContent}>
            {IconsModule?.Chevron && <IconsModule.Chevron direction="left" className={b?.Icon} />}
          </div>
        </DialogButton>
        {title}
      </DialogHeader>
      {children}
    </Focusable>
  );
}
