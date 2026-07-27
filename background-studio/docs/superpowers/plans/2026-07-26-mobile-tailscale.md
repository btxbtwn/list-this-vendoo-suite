# Background Studio Mobile and Tailscale Implementation Plan

> **For agentic workers:** Execute each checkbox in order and verify each observable result. Do not commit, push, or enable public Funnel.

**Goal:** Add a mobile-first responsive editor and private Tailnet HTTPS access without widening the backend network boundary.

**Architecture:** Keep FastAPI and Vite on loopback. Adapt the React/CSS layout below 720px and proxy the existing Vite service through private Tailscale Serve. Preserve relative `/api` calls so backend traffic stays on loopback.

**Tech Stack:** React, CSS, Vite, Vitest, Playwright, FastAPI, Tailscale Serve.

---

### Task 1: Responsive editor

**Files:**
- Modify: `frontend/src/App.jsx`
- Modify: `frontend/src/styles.css`
- Test: `frontend/src/App.test.jsx`

- [ ] Add minimal semantic wrappers/classes for mobile header, preview, controls, and export actions.
- [ ] Add a `<720px` single-column layout with 44px touch targets and no horizontal overflow.
- [ ] Size the preview stage with mobile viewport-aware bounds rather than the desktop 580px minimum.
- [ ] Keep exports visible in a sticky mobile action section without obscuring controls or the canvas.
- [ ] Preserve desktop layout and all brush/state behavior.
- [ ] Add focused responsive contract tests.

### Task 2: Tailnet-safe Vite configuration

**Files:**
- Modify: `frontend/vite.config.js`
- Modify: `README.md`
- Create: `scripts/start-private-tailnet.sh`

- [ ] Keep Vite bound to `127.0.0.1` on fixed port 5173 with strict-port behavior.
- [ ] Allow `criss-mac-mini-1.tail6c7361.ts.net` as a Vite host.
- [ ] Add a repeatable startup script for backend, frontend, and private Tailscale Serve without Funnel.
- [ ] Document the private HTTPS URL, shutdown command, and Tailnet-only security boundary.

### Task 3: Verification

- [ ] Run backend tests.
- [ ] Run frontend tests and production build.
- [ ] Run desktop E2E.
- [ ] Run browser checks at 320px, 375px, and 430px, including touch brush and export.
- [ ] Configure private Tailscale Serve and verify the HTTPS page plus `/api` proxy.
- [ ] Run clean Code Web Chat review and independent review against the final files.
