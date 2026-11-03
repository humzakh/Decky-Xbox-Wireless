import { ButtonItem, ConfirmModal, Field, PanelSection, PanelSectionRow, showModal } from "@decky/ui";
import { addEventListener, removeEventListener, toaster } from "@decky/api";
import { useEffect, useState } from "react";
import { DriverStatus, InstallInfo, STUCK_FIX, STUCK_TITLE, checkForUpdates, getDriverStatus, startInstall } from "./backend";
import { useXoneState } from "./useXoneState";

const LOG_LINES = 12;

function describe(status: DriverStatus) {
  if (status.installed_version && status.restart_needed) {
    return { label: `xone v${status.installed_version}`, description: "Restart to finish installing" };
  }
  if (status.installed_version) {
    const loaded = status.loaded_version ? "loaded" : "not loaded";
    return { label: `xone v${status.installed_version}`, description: `${loaded} · kernel ${status.kernel}` };
  }
  if (status.stale_versions.length > 0) {
    return {
      label: "Reinstall needed",
      description: "xone was built for a different kernel, probably before a SteamOS update.",
    };
  }
  return { label: "xone not installed", description: `Kernel ${status.kernel}` };
}

function updateAvailable(status: DriverStatus) {
  return !!status.installed_version && !!status.latest && status.latest.replace(/^v/, "") !== status.installed_version;
}

function confirmInstall(status: DriverStatus, title: string, onConfirm: () => void) {
  showModal(
    <ConfirmModal
      strTitle={title}
      strOKButtonText="OK"
      onOK={onConfirm}
      strDescription={
        <>
          Controllers disconnect while xone reloads. If they don't come back, unplug the adapter and plug it back in.
          {/* the firmware download is the one thing that needs consent */}
          {!status.firmware && (
            <p>The adapter firmware will be downloaded from Microsoft and is subject to Microsoft's Terms of Use.</p>
          )}
        </>
      }
    />,
  );
}

/** Driver status, install log and actions, shared by the panel and Steam's Controller page. */
function useDriver() {
  const [status, setStatus] = useState<DriverStatus | null>(null);
  const [lines, setLines] = useState<string[]>([]);
  const [checking, setChecking] = useState(false);

  const refresh = () =>
    getDriverStatus().then((s) => {
      setStatus(s);
      setLines(s.install?.log ?? []);
    });

  useEffect(() => {
    refresh();
    const onLog = addEventListener<[string]>("install_log", (line) => setLines((prev) => [...prev, line]));
    const onState = addEventListener<[InstallInfo]>("install_state", (install) => {
      setStatus((s) => (s ? { ...s, install } : s));
      if (!install.running) refresh();
    });
    return () => {
      removeEventListener("install_log", onLog);
      removeEventListener("install_state", onState);
    };
  }, []);

  if (!status) return null;

  const install = (tag: string | null, title: string) =>
    confirmInstall(status, title, async () => {
      setLines([]);
      const res = await startInstall(tag);
      if (!res.ok) toaster.toast({ title: "Xbox Wireless", body: res.error ?? "Install failed to start" });
    });

  const checkUpdates = async () => {
    setChecking(true);
    const s = await checkForUpdates();
    setStatus(s);
    setChecking(false);
    if (!s.latest) {
      toaster.toast({ title: "Xbox Wireless", body: "Couldn't reach GitHub to check for updates" });
    } else if (!updateAvailable(s)) {
      toaster.toast({ title: "Xbox Wireless", body: `xone ${s.latest} is the latest release` });
    }
  };

  const installed = status.installed_version ? `v${status.installed_version}` : null;
  return {
    status,
    lines,
    checking,
    running: !!status.install?.running,
    installed,
    ...describe(status),
    update: updateAvailable(status) ? () => install(status.latest, `Update xone to ${status.latest}`) : null,
    checkUpdates,
    reinstall: () => install(installed, `Reinstall xone ${installed}`),
    // not built for this kernel (e.g. after a SteamOS update): get the latest
    installLatest: () => install(null, `Install xone ${status.latest ?? ""}`.trim()),
  };
}

function installStatus(install: InstallInfo) {
  if (install.running) return `Installing ${install.tag}…`;
  return install.error ? `Failed: ${install.error}` : `Installed ${install.tag}`;
}

function InstallLog({ install, lines }: { install: InstallInfo; lines: string[] }) {
  return (
    <>
      <Field label={installStatus(install)} description={install.running ? undefined : `Full log: ${install.log_file}`} />
      <LogLines lines={lines} />
    </>
  );
}

function LogLines({ lines }: { lines: string[] }) {
  return (
    <div
      style={{
        fontFamily: "monospace",
        fontSize: "10px",
        lineHeight: 1.35,
        whiteSpace: "pre-wrap",
        wordBreak: "break-all",
        background: "rgba(0, 0, 0, 0.35)",
        borderRadius: "4px",
        padding: "6px",
        marginBottom: "8px",
      }}
    >
      {lines.slice(-LOG_LINES).join("\n") || "Starting…"}
    </div>
  );
}

/** The plugin panel's driver section. */
export function DriverSection() {
  const driver = useDriver();

  if (!driver) {
    return (
      <PanelSection title="xone driver">
        <PanelSectionRow>
          <Field label="Checking driver…" />
        </PanelSectionRow>
      </PanelSection>
    );
  }

  const { status, lines, checking, running, installed, label, description } = driver;
  return (
    <PanelSection title="xone driver">
      <PanelSectionRow>
        <Field label={label} description={description} />
      </PanelSectionRow>
      {installed ? (
        <>
          <PanelSectionRow>
            {driver.update ? (
              <ButtonItem layout="below" disabled={running} onClick={driver.update}>
                Update to {status.latest}
              </ButtonItem>
            ) : (
              <ButtonItem layout="below" disabled={running || checking} onClick={driver.checkUpdates}>
                {checking ? "Checking…" : "Check for updates"}
              </ButtonItem>
            )}
          </PanelSectionRow>
          <PanelSectionRow>
            <ButtonItem layout="below" disabled={running} onClick={driver.reinstall}>
              {running ? "Installing…" : "Reinstall driver"}
            </ButtonItem>
          </PanelSectionRow>
        </>
      ) : (
        <PanelSectionRow>
          <ButtonItem layout="below" disabled={running} onClick={driver.installLatest}>
            {running ? "Installing…" : "Install driver"}
          </ButtonItem>
        </PanelSectionRow>
      )}
      {status.install && (
        <PanelSectionRow>
          <InstallLog install={status.install} lines={lines} />
        </PanelSectionRow>
      )}
    </PanelSection>
  );
}

/** The same, as rows for a section of Steam's Controller settings page. */
export function DriverSettingsRows() {
  const driver = useDriver();
  const state = useXoneState();
  if (!driver) return <Field label="Checking driver…" />;

  const { status, lines, checking, running, installed, label, description } = driver;
  const install = status.install;
  // one row: what's installed, its install log once there is one, and the one action that fits;
  // reinstalling is left to the plugin panel
  const [action, onClick] = !installed
    ? ["Install", driver.installLatest]
    : driver.update
      ? [`Update to ${status.latest}`, driver.update]
      : [checking ? "Checking…" : "Check For Updates", driver.checkUpdates];
  return (
    <>
      {state?.dongles.some((d) => d.stuck) && <Field label={STUCK_TITLE} description={STUCK_FIX} />}
      <ButtonItem
        label={installed ? `Driver: xone ${installed}` : label}
        description={
          install ? (
            <>
              {installStatus(install)}
              {!install.running && ` · Full log: ${install.log_file}`}
              <LogLines lines={lines} />
            </>
          ) : (
            description
          )
        }
        layout="inline"
        disabled={running || checking}
        onClick={onClick}
      >
        {running ? "Installing…" : action}
      </ButtonItem>
    </>
  );
}
