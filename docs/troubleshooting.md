# Troubleshooting

## API Offline

Restart the app. If the packaged app still shows API offline, open Settings and export diagnostics. The Tauri app should start `rivenforge-api.exe` automatically from the same install folder as `rivenforge.exe`.

## OCR Looks Wrong

Use Manual Analyze with crop mode `full` first. Then try `single_card` for centered one-card screenshots or `new_card` for the new right-side roll in comparison view.

Bad or incomplete OCR should produce `REVIEW`. If it produces a confident but incorrect parse, save the screenshot as a fixture for regression testing.

## Clipboard Paste Fails

Some Windows apps do not expose image clipboard data in a browser-compatible format. Save the screenshot as a PNG and use Choose File.

## Diagnostics

Settings can export `rivenforge-diagnostics.zip`. The bundle is generated locally and includes app version, OS info, dependency versions, config summary, and recent logs. It does not include screenshots by default.
