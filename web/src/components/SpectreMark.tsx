/**
 * SPECTRE lockup: the PEAK mark beside the phosphor wordmark.
 * The mark is drawn with the theme variables, so it follows the active skin.
 * Author: gurvinny
 */
import { cn } from "@/lib/utils";

/** The PEAK mark: a spectrum trace with one channel peak and the threat point on top. */
export function PeakMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 64 64" aria-hidden="true" className={cn("shrink-0", className)}>
      <rect x="3.5" y="3.5" width="57" height="57" rx="13" fill="var(--color-scope-bg)"
        stroke="var(--color-phosphor-dim)" strokeWidth="3" />
      <path d="M11 47 H18.5 L22 40.5 L25.5 45 L32 18 L38.5 45 L42 40.5 L45.5 47 H53" fill="none"
        stroke="var(--color-phosphor)" strokeWidth="5" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx="32" cy="14" r="5.6" fill="var(--color-alert)" />
    </svg>
  );
}

export function SpectreMark({
  size = "md",
  subtitle = true,
}: {
  size?: "sm" | "md" | "lg";
  subtitle?: boolean;
}) {
  const scale =
    size === "lg" ? "text-3xl" : size === "sm" ? "text-base" : "text-xl";
  const mark = size === "lg" ? "h-11 w-11" : size === "sm" ? "h-6 w-6" : "h-8 w-8";
  return (
    <div className="flex items-center gap-2.5">
      <PeakMark className={mark} />
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
    </div>
  );
}
