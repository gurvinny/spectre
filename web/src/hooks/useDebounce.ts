/** Debounce a rapidly-changing value (e.g. a search box). Author: gurvinny */
"use client";

import { useEffect, useState } from "react";

export function useDebounce<T>(value: T, ms = 180): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const id = setTimeout(() => setDebounced(value), ms);
    return () => clearTimeout(id);
  }, [value, ms]);
  return debounced;
}
