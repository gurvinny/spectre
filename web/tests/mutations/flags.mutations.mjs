// Build-time feature flags: experimental views stay out unless enabled.
export const TARGET = "src/lib/flags.ts";
export const TESTS = "src/lib/flags.test.ts";
export const MUTATIONS = [
  ["any-value-enables", '  return value?.trim().toLowerCase() === "true";', "  return Boolean(value);",
   "only an explicit true enables experimental views"],
  ["case-sensitive", '  return value?.trim().toLowerCase() === "true";', '  return value?.trim() === "true";',
   "only an explicit true enables experimental views"],
  ["untrimmed", '  return value?.trim().toLowerCase() === "true";', '  return value?.toLowerCase() === "true";',
   "only an explicit true enables experimental views"],
  ["experimental-always-shown", "  return items.filter((i) => experimental || !i.experimental);", "  return items;",
   "experimental entries are hidden unless enabled, order kept"],
  ["experimental-never-shown", "  return items.filter((i) => experimental || !i.experimental);",
   "  return items.filter((i) => !i.experimental);",
   "experimental entries are hidden unless enabled, order kept"],
];
