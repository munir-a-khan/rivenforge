# Background OCR And Automation

This note captures the current technical boundary for running rivenforge while
the user is focused on another window.

## What Should Work

OCR can work while Warframe is not focused if the Warframe frame is still
visible on the desktop. Examples:

- Warframe is borderless/windowed on a second monitor.
- Warframe is visible in the background and not covered by another window.
- The user is focused in another app on a different monitor.

In these cases, normal desktop capture (`mss`) or DXGI capture (`dxcam`) can
still see the pixels that OCR needs.

## What Is Not Supported

True hidden-window rolling is not supported:

- Warframe minimized.
- Warframe fully covered by another window on the same monitor.
- Warframe running behind another fullscreen app.

The current capture stack reads the composed desktop. If Warframe is not
visible in that composed desktop, there are no riven card pixels for OCR to
read. Capturing an occluded DirectX game window reliably would require riskier
approaches outside this project's safety boundaries.

## Input Limitation

Warframe ignores the safer background click methods tested so far. The current
automation path uses real cursor movement and hardware-style mouse/key events,
which means Warframe generally must be the active foreground target when the app
clicks `CYCLE`, `YES`, `NO`, or `CONFIRM`.

That is why fully background rolling on the same monitor is not currently a
realistic goal without changing the safety model. The safer direction is:

- support visible-but-unfocused OCR,
- keep manual analysis fully usable without game focus,
- make stop/kill behavior reliable,
- avoid memory reading, injection, hidden hooks, or anti-detection behavior.

## Current Stop Behavior

`Ctrl+Shift+Q` is registered by the Tauri shell as a global emergency stop. The
native hotkey handler now posts directly to the local sidecar's `/roll/stop`
endpoint, then also notifies React for UI feedback. This avoids relying only on
the webview event path.

The Python stop/finish/error paths also release common stuck input state
(Alt/Ctrl/Shift and mouse buttons) to reduce cases where Warframe or Windows
feels trapped after a failed automation action.
