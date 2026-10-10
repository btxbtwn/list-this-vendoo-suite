/**
 * The UI bundle knows which version it was built from; the backend reports the
 * version it was installed as. When an update replaces the Python side but
 * leaves a stale `dist/` behind, those disagree — and that used to be invisible,
 * because the status bar read the backend's number while showing the old UI.
 */
export type BuildState = {
  /** What the running bundle was built from. */
  version: string;
  /** True when the backend has moved on and this bundle has not. */
  outdated: boolean;
  label: string;
  title: string | undefined;
};

export function frontendBuildState(
  build: { version: string; short_sha: string },
  backendVersion: string | null | undefined,
): BuildState {
  const version = build.version || "0.0.0";
  const backend = (backendVersion || "").trim();
  const outdated = Boolean(backend) && backend !== version;
  return {
    version,
    outdated,
    label: outdated ? `V ${version} (stale)` : `V ${version}`,
    title: outdated
      ? [
          `This window is running the ${version} UI${build.short_sha ? ` (${build.short_sha})` : ""}.`,
          `Studio itself is on ${backend}.`,
          "Reload the page. If it keeps saying stale, the interface did not rebuild after the last update:",
          "quit and reopen List This Studio; it rebuilds the interface on launch, or reinstall from the latest release.",
        ].join(" ")
      : undefined,
  };
}

const RELOADED_KEY = "studio.reloaded-for";

/** Whether to reload now for `backendVersion`: once per backend version per tab, so a bundle
 * that is stale on disk does not reload forever. */
export function reloadForBackend(backendVersion: string, storage: Pick<Storage, "getItem" | "setItem">): boolean {
  if (!backendVersion || storage.getItem(RELOADED_KEY) === backendVersion) return false;
  storage.setItem(RELOADED_KEY, backendVersion);
  return true;
}
