# rivenforge companion (Android)

A private companion app for rivenforge license holders: pair with your PC, then
**watch your riven rolls live on your phone** while a session runs at home. It
reads the roll stream over your network — it does **not** roll on the phone.

> Scaffold status: this is a complete, buildable-in-Android-Studio starting
> point, **not** a pre-built APK. It was authored without an Android build
> environment, so treat dependency versions as a starting point and let Android
> Studio's sync suggest bumps. Nothing here is on the Play Store — it's for the
> private, license-only distribution (sideload / Play internal track).

## What it does (v1)

- **Pair** by scanning the QR in the desktop app (Settings → Phone Access), or
  paste the `rivenforge://pair?host=…&port=…&token=…` code by hand.
- **Live view:** connects to `ws://<pc>:47321/events?token=…` and shows each
  roll as it happens — stats, the keep/revert decision, and running score.
- **Session banner:** `GET /roll/session` shows what's running (weapon, limit).
- **Stop** the session remotely (`POST /roll/stop`). Pause/edit come later
  (the sidecar needs a pause endpoint first — see `docs/android-companion.md`).

## Connecting

1. On the PC: Settings → **Phone Access** → enable, then **restart the app** so
   the sidecar binds your network. A QR code appears.
2. On the phone: **Pair** → scan the QR.
3. At home you're on the same Wi‑Fi, so the LAN IP in the QR just works. Away
   from home, run **Tailscale** on both devices and pair with the PC's tailnet
   IP instead (re-generate the code after connecting Tailscale, or edit the host
   in the paste field).

The pairing token is a bearer secret. Anyone with it can watch/stop your
session, so treat it like a password; **Revoke** on the desktop kills it.

## Build

Open the `android/` folder in Android Studio (Ladybug or newer), let it sync,
then Run on a device/emulator. Or from a shell with the Android SDK configured:

```bash
cd android
./gradlew assembleDebug        # app/build/outputs/apk/debug/app-debug.apk
```

## Security notes

- Talks plain HTTP/WS on the LAN (`usesCleartextTraffic`), gated by the token.
  Fine for a home network; over the internet use Tailscale (encrypted transit).
- The token is stored in `SharedPreferences`. Hardening TODO: move it to
  `EncryptedSharedPreferences` (Android Keystore) — noted in `Pairing.kt`.

## Layout

```
android/
  settings.gradle.kts, build.gradle.kts, gradle.properties
  app/
    build.gradle.kts
    src/main/AndroidManifest.xml
    src/main/java/com/rivenforge/companion/
      MainActivity.kt        # Compose host + navigation
      Pairing.kt             # parse rivenforge:// code, persist creds
      RivenforgeClient.kt    # OkHttp WS + HTTP, event → UI model
      Models.kt              # RollItem / SessionInfo / ConnState
      ui/AppUi.kt            # Pair screen + Live screen
    src/main/res/…           # theme, strings, network config
```
