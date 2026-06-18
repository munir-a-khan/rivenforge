# Security And Safety

rivenforge is a local desktop assistant. It should not:

- Read game memory.
- Inject into the game process.
- Inspect packets.
- Hide background behavior.
- Install kernel drivers.
- Attempt anti-detection bypasses.
- Upload screenshots or user data automatically.

The local API binds to `127.0.0.1` only. Diagnostic bundles are written locally and shared only if the user chooses to export them.

## Release Safety Checklist

- Verify the sidecar binds to localhost.
- Verify automation is optional.
- Verify low-confidence OCR returns `REVIEW`.
- Verify diagnostics do not include screenshots unless explicitly enabled later.
- Run dependency and packaging checks before publishing.
