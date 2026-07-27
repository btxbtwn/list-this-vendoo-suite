# Background Studio Mobile and Tailscale Design

## Goal

Make Background Studio comfortable and fully functional on phones while keeping remote access private to Cristian's Tailscale network.

## Mobile interface

Desktop keeps the existing two-column workspace. At widths below 720px, the editor becomes a single column: compact header, preview canvas first, controls below, and exports in a sticky bottom action section. The page must not scroll horizontally at 320px, 375px, or 430px. Interactive controls use at least 44px touch targets, range controls remain usable with touch, and the preview stage uses the available viewport without forcing a tall desktop-sized canvas.

The existing visual language stays intact. This is a responsive adaptation, not a redesign. Brush behavior, operation ownership, keyboard access, previews, and export semantics remain unchanged.

## Private Tailscale access

Vite remains bound to `127.0.0.1:5173` and continues proxying `/api` to the loopback FastAPI service at `127.0.0.1:8000`. Tailscale Serve terminates private Tailnet HTTPS at `https://criss-mac-mini-1.tail6c7361.ts.net` and proxies to Vite. Funnel remains disabled.

Because the browser reaches Vite through Tailscale Serve and Vite reaches FastAPI over loopback, FastAPI's loopback-only middleware remains unchanged. Vite explicitly allows the MagicDNS hostname.

## Verification

Automated tests cover responsive structure and required touch-target classes/contracts. Browser checks run at 320px, 375px, and 430px for overflow, stage sizing, controls, touch drawing, and export availability. A live Tailnet check verifies the HTTPS page and API proxy, then upload, brush, and export through the private URL.

## Safety

Do not use Tailscale Funnel. Do not bind FastAPI or Vite to `0.0.0.0`. Do not expose model caches, credentials, environment files, or temporary job storage. No commit, push, or deployment is part of this change.
