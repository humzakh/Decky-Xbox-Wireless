import { ToggleField } from "@decky/ui";
import { useEffect, useState } from "react";
import { getSettings, reportError, setSetting } from "./backend";

// mirrors mix() in py_modules/chat_mix.py
const DIAL_CENTER = 50;
const FADE_DB = 30;

const fade = (amount: number) => (amount >= 1 ? 0 : 10 ** ((-FADE_DB * amount) / 60));

function mixText(dial: number) {
  const game = dial <= DIAL_CENTER ? 1 : fade((dial - DIAL_CENTER) / (100 - DIAL_CENTER));
  const chat = dial <= DIAL_CENTER ? fade((DIAL_CENTER - dial) / DIAL_CENTER) : 1;
  return `Game ${Math.round(game * 100)}% · Chat ${Math.round(chat * 100)}%`;
}

/** Whether the headset's dial balances chat apps against game audio. */
export function ChatMixToggle({ dial }: { dial: number }) {
  const [enabled, setEnabled] = useState<boolean | null>(null);
  useEffect(() => {
    getSettings().then((s) => setEnabled(s.chat_mix));
  }, []);

  return (
    <ToggleField
      label="Game/chat dial"
      description={enabled ? mixText(dial) : "Discord and Steam voice chat against everything else"}
      checked={!!enabled}
      disabled={enabled === null}
      onChange={async (value) => {
        setEnabled(value);
        reportError(await setSetting("chat_mix", value));
      }}
    />
  );
}
