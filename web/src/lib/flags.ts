/**
 * Build-time feature flags. NEXT_PUBLIC_* values are inlined when the bundle is
 * built, so a flag changes with a rebuild, not a restart.
 * Author: gurvinny
 */

/** Experimental views (the 3D battlespace) stay out of the console unless the
 *  build sets NEXT_PUBLIC_EXPERIMENTAL=true. */
export function experimentalEnabled(value: string | undefined): boolean {
  return value?.trim().toLowerCase() === "true";
}

export const EXPERIMENTAL = experimentalEnabled(process.env.NEXT_PUBLIC_EXPERIMENTAL);

export interface NavItem<I = unknown> {
  href: string;
  label: string;
  icon: I;
  experimental?: boolean;
}

/** The sidebar entries to show for this build. */
export function visibleNav<I>(items: NavItem<I>[], experimental: boolean): NavItem<I>[] {
  return items.filter((i) => experimental || !i.experimental);
}
