import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { applyTheme, normalizeTheme, type ThemePreference } from "../theme";

/** Keep `data-theme` in sync with Settings → Appearance (and the OS when System). */
export function ThemeSync() {
  const { data } = useQuery({
    queryKey: ["settings-ui"],
    queryFn: api.settings.ui,
  });
  const preference: ThemePreference = normalizeTheme(data?.theme);

  useEffect(() => {
    applyTheme(preference);
  }, [preference]);

  useEffect(() => {
    if (preference !== "system") return;
    const media = window.matchMedia("(prefers-color-scheme: light)");
    const onChange = () => applyTheme("system");
    media.addEventListener("change", onChange);
    return () => media.removeEventListener("change", onChange);
  }, [preference]);

  return null;
}
