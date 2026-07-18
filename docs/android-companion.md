# Android Companion — Design Notes

Goal: pause/resume a rolling session, edit profiles, and watch the roll log
from a phone while the PC keeps rolling. Nothing here is built yet; this is the
plan and, more importantly, the list of things in the current codebase that
have to change first.

## What already exists (and is reusable as-is)

The desktop sidecar is already a plain HTTP + WebSocket server, which is most of
a phone backend:

| Need on phone | Existing endpoint | Reusable? |
| --- | --- | --- |
| Live roll log | `WS /events` | Yes — already streams every roll event |
| Pause / resume | `POST /roll/stop`, `POST /roll/start` | Stop yes; **pause does not exist** |
| Edit rolls/profiles | `GET /config`, `PUT /config` | Yes |
| Weapon + stat pickers | `GET /weapons`, `GET /stats` | Yes |
| Session state | — | **Missing** — no "am I running?" endpoint |

So the companion app is mostly a second client against the same API. The hard
parts are not the screens; they are reachability, auth, and the two missing
capabilities.

## Blockers in the current code

### 1. The sidecar is localhost-only, on purpose

`api/app.py` binds `127.0.0.1:47321`. A phone on the same Wi-Fi cannot reach
that. Binding `0.0.0.0` is a one-line change and a genuinely bad idea until
auth exists — today every endpoint is unauthenticated because "only this
machine can talk to it" was the entire security model. Opening the bind
without auth first would expose `PUT /config` and `POST /roll/start` to
anything on the network.

**Order matters: auth lands before the bind changes.**

### 2. There is no pause — only stop

`POST /roll/stop` tears the session down. The user's ask ("pause from my
phone, edit, resume") needs the session to stay alive and hold its state
(roll count, current weapon, blacklist) across a pause. That's a change in
`api/sessions.py` + `core/roller.py`: a pause event the roll loop checks
between rolls, plus `POST /roll/pause` and `POST /roll/resume`.

Pausing must land **between** rolls, never mid-roll — stopping halfway through
a cycle/confirm sequence could leave the riven UI in a state the next resume
misreads.

### 3. No session-state endpoint

The desktop UI tracks `running` in React state, which works because it is the
thing that started the session. A phone joining late has no way to ask. Needs
`GET /roll/session` returning `{running, paused, rolls_done, roll_limit, weapon}`.

## Reachability — the real decision

| Option | Cost | Works outside home? | Notes |
| --- | --- | --- | --- |
| **LAN direct** (phone → PC IP) | $0 | No | Simplest. Covers "on the couch / in bed", which is the stated use case. |
| Tailscale / WireGuard | $0 (personal tier) | Yes | User installs Tailscale both sides; phone reaches the PC by its tailnet IP. No code change beyond LAN support. |
| Relay server | Hosting $ + maintenance | Yes | Rejected — recurring cost, and it puts rolls through a third box. |

**Recommendation: build LAN direct, document Tailscale as the remote path.**
Both are the same code — the phone just points at a different address — so
"from bed" works day one and "from work" works for anyone willing to install
Tailscale. No server, no monthly cost, consistent with the offline-license
decision.

## Auth for the phone

The Ed25519 license system now in `core/license.py` authorizes *the app*, not
*a caller* — it is the wrong tool here, and the license key must never be sent
to the phone as a bearer token (it would leak the thing that gates automation).

Use a separate **pairing token**:

1. Desktop generates a random 32-byte token, shows it as a QR code.
2. Phone scans it, stores it in Android Keystore.
3. Phone sends `Authorization: Bearer <token>` on every request.
4. Sidecar rejects non-localhost requests without a valid token.

Localhost keeps its current no-auth path so the desktop UI and all existing
tests are untouched. This is a middleware in `api/app.py` gated on
`request.client.host != "127.0.0.1"`.

Plain HTTP over a trusted LAN is acceptable for v1 (TLS needs a cert story that
self-signed certs make painful on Android). Worth stating plainly in the UI
rather than implying more security than there is.

## Suggested build order

1. `POST /roll/pause` + `/roll/resume` + `GET /roll/session` — useful on
   desktop too, independent of any phone work.
2. Pairing token + bearer middleware + `--host` flag on the sidecar.
3. Desktop Settings: "Phone Access" card — enable, show QR, revoke.
4. Android client (Kotlin + Compose): pair → session screen (pause/resume,
   live log via the existing `/events` socket) → profile editor against
   `/config`.
5. Play Store: needs a privacy policy, a signing key, and a listing. The app
   talks only to the user's own PC, which keeps the data-safety form simple.

## Open questions

- Does the roll log need history on the phone, or is live-tail enough? There is
  no history endpoint today — `/events` is a live stream only, so a phone that
  connects mid-session sees nothing that already happened. If history matters,
  `core/roll_logger.py` already writes it to disk and would need an endpoint.
- Should the phone be able to *start* a session, or only pause/edit an existing
  one? Starting remotely means nobody is watching the game — worth a deliberate
  decision rather than falling out of the API surface.
