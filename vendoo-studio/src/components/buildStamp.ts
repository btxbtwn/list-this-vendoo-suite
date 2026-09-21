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
          "The interface did not rebuild after the last update. Quit and reopen List This Studio;",
          "it rebuilds the interface on launch. If it keeps saying stale, reinstall from the latest release.",
        ].join(" ")
      : undefined,
  };
}
