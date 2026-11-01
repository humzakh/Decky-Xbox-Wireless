import { CSSProperties } from "react";
import { PiHeadsetFill } from "react-icons/pi";

// Mirrored so the mic is on the left.
export function HeadsetIcon({ className, style }: { className?: string; style?: CSSProperties }) {
  return <PiHeadsetFill className={className} style={{ transform: "scaleX(-1)", ...style }} />;
}
