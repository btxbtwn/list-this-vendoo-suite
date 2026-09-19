/** Official marketplace logos from Vendoo's symbols-logo set. */

import { useId } from "react";
import { OFFICIAL_LOGOS, hasOfficialLogo, type OfficialLogo } from "./marketplaceLogos";

export { hasOfficialLogo as hasMarketplaceLogo };

export function marketplaceLogoColor(id: string): string {
  const logo = OFFICIAL_LOGOS[id];
  if (!logo) return "#5C6578";
  const solid = logo.paths.map((p) => p.fill).find((f) => f && !f.startsWith("url("));
  return solid || "#5C6578";
}

function GradientDefs({
  logo,
  prefix,
}: {
  logo: OfficialLogo;
  prefix: string;
}) {
  if (!logo.defs?.length) return null;
  return (
    <defs>
      {logo.defs.includes("a") ? (
        <linearGradient id={`${prefix}-a`} x1="17.6%" y1="74.5%" x2="84.8%" y2="20.1%">
          <stop stopColor="#FECB40" offset="0%" />
          <stop stopColor="#F7507C" offset="30.9%" />
          <stop stopColor="#4852E8" offset="63.9%" />
          <stop stopColor="#47CDAE" offset="100%" />
        </linearGradient>
      ) : null}
      {logo.defs.includes("paint0_radial_86_2295") ? (
        <radialGradient
          id={`${prefix}-paint0_radial_86_2295`}
          cx="0"
          cy="0"
          r="1"
          gradientUnits="userSpaceOnUse"
          gradientTransform="matrix(0 22.9085 -23.3737 0 24 23)"
        >
          <stop offset="0.17" stopColor="#273517" />
          <stop offset="0.53" stopColor="#728C55" />
          <stop offset="1" stopColor="#B4CB26" />
        </radialGradient>
      ) : null}
    </defs>
  );
}

function remapFill(fill: string | undefined, prefix: string): string | undefined {
  if (!fill) return undefined;
  const m = /^url\(#(.+)\)$/.exec(fill);
  if (!m) return fill;
  return `url(#${prefix}-${m[1]})`;
}

export function MarketplaceLogo({
  id,
  label,
  size = 16,
}: {
  id: string;
  label: string;
  size?: number;
}) {
  const reactId = useId().replace(/:/g, "");
  const prefix = `mpl-${reactId}`;
  const logo = OFFICIAL_LOGOS[id];

  if (logo) {
    return (
      <span
        className="marketplace-logo"
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
          <GradientDefs logo={logo} prefix={prefix} />
          {logo.paths.map((path, index) => (
            <path
              key={index}
              d={path.d}
              fill={remapFill(path.fill, prefix)}
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
      className="marketplace-logo marketplace-logo-fallback"
      title={label}
      aria-label={label}
      style={{ width: size, height: size }}
    >
      <span className="marketplace-logo-letter" aria-hidden="true">
        {letter}
      </span>
    </span>
  );
}
