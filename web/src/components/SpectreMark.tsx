/**
 * SPECTRE wordmark lockup — the phosphor brand signature.
 * Author: gurvinny
 */
import { cn } from "@/lib/utils";

export function SpectreMark({
  size = "md",
  subtitle = true,
}: {
  size?: "sm" | "md" | "lg";
  subtitle?: boolean;
}) {
  const scale =
    size === "lg" ? "text-3xl" : size === "sm" ? "text-base" : "text-xl";
  return (
    <div className="flex flex-col gap-0.5">
      <div className={cn("font-display font-700 tracking-[0.32em] text-phosphor phosphor-glow leading-none", scale)}>
        SPECTRE
      </div>
      {subtitle && (
        <div className="eyebrow text-[0.55rem]">
          Electromagnetic Threat Reconnaissance
        </div>
      )}
    </div>
  );
}
