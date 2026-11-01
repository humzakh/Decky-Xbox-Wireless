import { SliderField } from "@decky/ui";
import { useRef, useState } from "react";
import { Client, reportError, resetLed, setLed } from "./backend";

/** Guide button LED brightness for a client that has an LED. */
export function LedSlider({ client }: { client: Client }) {
  const led = client.led!;
  const [dragged, setDragged] = useState<number | null>(null);
  const debounce = useRef<ReturnType<typeof setTimeout>>(undefined);

  return (
    <SliderField
      label="LED brightness"
      value={dragged ?? led.brightness}
      min={0}
      max={led.max_brightness}
      step={1}
      showValue
      resetValue={led.default_brightness}
      onChange={(value) => {
        setDragged(value);
        clearTimeout(debounce.current);
        debounce.current = setTimeout(async () => {
          // back at the default: forget the saved brightness rather than pin it
          const atDefault = value === led.default_brightness;
          reportError(await (atDefault ? resetLed(client.id) : setLed(client.id, value, null)));
          setDragged(null);
        }, 200);
      }}
    />
  );
}
