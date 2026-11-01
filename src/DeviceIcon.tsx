import { PiKeyboardFill } from "react-icons/pi";
import { Client } from "./backend";
import { HeadsetIcon } from "./HeadsetIcon";
import { SteamControllerIcon } from "./SteamControllerIcon";

export function DeviceIcon({ client }: { client: Client }) {
  switch (client.kind) {
    case "headset":
      // xone doesn't expose whether a mic is fitted; GIP headsets all announce mic input
      return <HeadsetIcon />;
    case "chatpad":
      return <PiKeyboardFill />;
    default:
      return <SteamControllerIcon />;
  }
}
