import { useEffect, useState } from "react";
import { Dongle, State } from "./backend";

/** Seconds of pairing mode left on a dongle (the full timeout when it isn't pairing). */
export function usePairingCountdown(state: State | null) {
  const [now, setNow] = useState(Date.now() / 1000);
  const anyPairing = !!state?.dongles.some((d) => d.pairing);
  useEffect(() => {
    if (!anyPairing) return;
    const timer = setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => clearInterval(timer);
  }, [anyPairing]);
  return (dongle: Dongle) => {
    const started = state?.pairing_started[dongle.id];
    if (started === undefined) return state?.pairing_timeout ?? 60;
    return Math.max(0, Math.ceil(started + (state?.pairing_timeout ?? 60) - now));
  };
}
