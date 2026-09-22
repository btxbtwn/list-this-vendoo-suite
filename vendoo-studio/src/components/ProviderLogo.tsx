/** Listing AI provider logos for Settings and the status bar. */

import {
  PROVIDER_LOGOS,
  hasProviderLogo,
  resolveProviderLogoId,
  type ProviderLogoId,
} from "./providerLogos";

export { hasProviderLogo, resolveProviderLogoId };
export type { ProviderLogoId };

export function providerLogoColor(id: string): string {
  if (!hasProviderLogo(id)) return "#5C6578";
  return PROVIDER_LOGOS[id].color;
}

export function ProviderLogo({
  id,
  label,
  size = 16,
}: {
  id: string;
  label: string;
  size?: number;
}) {
  const logo = hasProviderLogo(id) ? PROVIDER_LOGOS[id] : null;

  if (logo) {
    return (
      <span
        className="provider-logo"
        title={label}
        aria-label={label}
        style={{ width: size, height: size }}
      >
        <svg
          width={size - 2}
          height={size - 2}
          viewBox={logo.viewBox}
          preserveAspectRatio="xMidYMid meet"
          aria-hidden="true"
        >
          {logo.paths.map((path, index) => (
            <path
              key={index}
              d={path.d}
              fill={path.fill || logo.color}
              fillRule={path.fillRule}
              clipRule={path.clipRule}
            />
          ))}
        </svg>
      </span>
    );
  }

  const letter = (label || id || "?").trim().charAt(0).toUpperCase() || "?";
  return (
    <span
      className="provider-logo provider-logo-fallback"
      title={label}
      aria-label={label}
      style={{ width: size, height: size }}
    >
      <span className="provider-logo-letter" aria-hidden="true">
        {letter}
      </span>
    </span>
  );
}
