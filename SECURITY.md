# Security

Report vulnerabilities privately through GitHub Security Advisories on this repository. Do not open a public issue for a security report.

Never commit API keys, OAuth credentials, listing photos, generated diagnostics, or private exports. Keys stay in macOS Keychain and must not enter SQLite, logs, frontend responses, or extension messages.

Studio binds only to `127.0.0.1`. Automation must stop at saved drafts and require a person before anything is sent or published.

The extension pairs with Studio through a token served at `GET /api/extension/pairing-token`. That endpoint has no authentication. Browser pages on other origins cannot read it because of CORS, but any process running as the same user on the Mac can. The token only lets a client act as the extension over the loopback websocket. It never grants access to API keys.
