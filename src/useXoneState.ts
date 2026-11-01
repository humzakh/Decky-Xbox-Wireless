import { addEventListener, removeEventListener } from "@decky/api";
import { useEffect, useState } from "react";
import { State, getState } from "./backend";

/** The backend's latest snapshot of dongles and devices; null until it first arrives. */
export function useXoneState() {
  const [state, setState] = useState<State | null>(null);

  useEffect(() => {
    getState().then(setState);
    const listener = addEventListener<[State]>("state", setState);
    return () => removeEventListener("state", listener);
  }, []);

  return state;
}
