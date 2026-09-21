import { frontendBuildState } from "./buildStamp";

export function BuildVersion({ backendVersion }: { backendVersion: string | null | undefined }) {
  const state = frontendBuildState(__STUDIO_BUILD__, backendVersion);
  return (
    <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
      {state.outdated && <span className="status-dot outdated" />}
      <span className={state.outdated ? "status-outdated" : undefined} title={state.title}>
        {state.label}
      </span>
    </span>
  );
}
