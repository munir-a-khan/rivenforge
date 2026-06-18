use std::collections::VecDeque;
use std::io::Write;
use std::net::TcpStream;
use std::sync::{Arc, Mutex};
use std::time::Duration;

use serde_json::Value;
use tauri::{Emitter, State};
use tauri_plugin_global_shortcut::{Code, GlobalShortcutExt, Modifiers, Shortcut, ShortcutState};
use tauri_plugin_shell::{
    process::{CommandChild, CommandEvent},
    ShellExt,
};

/// Emergency-stop hotkey label, surfaced to the React shell so the footer
/// chip always matches what the OS is actually listening for. Update this
/// const and the Shortcut below together.
const HOTKEY_LABEL: &str = "Ctrl+Shift+Q";

const FIXED_API_HOST: &str = "127.0.0.1";
const FIXED_API_PORT: u16 = 47321;
const FIXED_API_BASE: &str = "http://127.0.0.1:47321";
const SIDECAR_LOG_LINES: usize = 200;

#[derive(Default)]
struct SidecarState {
    api_base: Mutex<Option<String>>,
    child: Mutex<Option<CommandChild>>,
    /// Tail of recent stderr/stdout from the sidecar. Surfaced via
    /// `get_sidecar_logs` so Settings can show what actually broke.
    log_tail: Mutex<VecDeque<String>>,
}

impl SidecarState {
    fn push_log(&self, line: String) {
        if let Ok(mut tail) = self.log_tail.lock() {
            if tail.len() == SIDECAR_LOG_LINES {
                tail.pop_front();
            }
            tail.push_back(line);
        }
    }
}

#[tauri::command]
fn get_sidecar_api_base(state: State<'_, Arc<SidecarState>>) -> Option<String> {
    state.api_base.lock().ok().and_then(|value| value.clone())
}

#[tauri::command]
fn get_hotkey_label() -> &'static str {
    HOTKEY_LABEL
}

#[tauri::command]
fn get_sidecar_logs(state: State<'_, Arc<SidecarState>>) -> Vec<String> {
    state
        .log_tail
        .lock()
        .map(|tail| tail.iter().cloned().collect())
        .unwrap_or_default()
}

fn parse_ready_line(line: &str) -> Option<String> {
    let payload = line.strip_prefix("RIVENFORGE_API_READY ")?;
    let parsed: Value = serde_json::from_str(payload).ok()?;
    let host = parsed.get("host")?.as_str()?;
    let port = parsed.get("port")?.as_u64()?;
    Some(format!("http://{host}:{port}"))
}

/// True iff something is already listening on the fixed sidecar port —
/// usually an orphan from a previous launch we should reuse, not duplicate.
fn fixed_port_already_listening() -> bool {
    TcpStream::connect_timeout(
        &format!("{FIXED_API_HOST}:{FIXED_API_PORT}").parse().unwrap(),
        Duration::from_millis(300),
    )
    .is_ok()
}

fn post_stop_to_sidecar() -> std::io::Result<()> {
    let mut stream = TcpStream::connect_timeout(
        &format!("{FIXED_API_HOST}:{FIXED_API_PORT}").parse().unwrap(),
        Duration::from_millis(350),
    )?;
    stream.set_write_timeout(Some(Duration::from_millis(350)))?;
    stream.write_all(
        b"POST /roll/stop HTTP/1.1\r\nHost: 127.0.0.1:47321\r\nContent-Length: 0\r\nConnection: close\r\n\r\n",
    )?;
    stream.flush()?;
    Ok(())
}

fn main() {
    let sidecar_state = Arc::new(SidecarState::default());
    let managed_state = Arc::clone(&sidecar_state);
    let shutdown_state = Arc::clone(&sidecar_state);
    let hotkey_state = Arc::clone(&sidecar_state);

    // Ctrl+Shift+Q — the emergency stop hotkey. Registered globally so it
    // fires while Warframe (or anything else) has keyboard focus. The
    // handler emits an event the React shell listens for; the shell then
    // POSTs /roll/stop. We do not call the sidecar directly from Rust to
    // avoid duplicating the API base resolution / retry logic that already
    // lives on the JS side.
    let stop_shortcut = Shortcut::new(
        Some(Modifiers::CONTROL | Modifiers::SHIFT),
        Code::KeyQ,
    );

    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(
            tauri_plugin_global_shortcut::Builder::new()
                .with_handler(move |app, shortcut, event| {
                    if event.state() == ShortcutState::Pressed && *shortcut == stop_shortcut {
                        let state = Arc::clone(&hotkey_state);
                        std::thread::spawn(move || match post_stop_to_sidecar() {
                            Ok(()) => state.push_log("tauri: hotkey posted /roll/stop".to_string()),
                            Err(error) => state.push_log(format!("tauri: hotkey stop failed: {error}")),
                        });
                        let _ = app.emit("rivenforge-hotkey-stop", HOTKEY_LABEL);
                    }
                })
                .build(),
        )
        .manage(managed_state)
        .invoke_handler(tauri::generate_handler![
            get_sidecar_api_base,
            get_sidecar_logs,
            get_hotkey_label
        ])
        .setup(move |app| {
            let app_handle = app.handle().clone();
            let state = Arc::clone(&sidecar_state);

            // Register the hotkey. If another process already owns the
            // combo (rare but possible), log it instead of crashing — the
            // GUI Stop button still works.
            if let Err(e) = app.global_shortcut().register(stop_shortcut) {
                eprintln!("global hotkey registration failed: {e}");
                state.push_log(format!("tauri: hotkey register failed: {e}"));
            } else {
                state.push_log(format!("tauri: hotkey registered ({HOTKEY_LABEL})"));
            }

            // If a previous launch left an orphan rivenforge-api alive on
            // the fixed port, skip spawning. We tell React the URL anyway
            // via the ready event so it can hit /health immediately.
            if fixed_port_already_listening() {
                if let Ok(mut value) = state.api_base.lock() {
                    *value = Some(FIXED_API_BASE.to_string());
                }
                let _ = app_handle.emit("rivenforge-api-ready", FIXED_API_BASE.to_string());
                state.push_log(
                    "tauri: detected existing rivenforge-api on 47321; reusing".to_string(),
                );
                return Ok(());
            }

            tauri::async_runtime::spawn(async move {
                let command = match app_handle.shell().sidecar("rivenforge-api").map(|cmd| {
                    cmd.args([
                        "--host",
                        FIXED_API_HOST,
                        "--port",
                        &FIXED_API_PORT.to_string(),
                    ])
                }) {
                    Ok(command) => command,
                    Err(error) => {
                        eprintln!("failed to prepare rivenforge-api sidecar: {error}");
                        state.push_log(format!("tauri: prepare failed: {error}"));
                        return;
                    }
                };

                let (mut events, child) = match command.spawn() {
                    Ok(spawned) => spawned,
                    Err(error) => {
                        eprintln!("failed to spawn rivenforge-api sidecar: {error}");
                        state.push_log(format!("tauri: spawn failed: {error}"));
                        return;
                    }
                };

                if let Ok(mut child_slot) = state.child.lock() {
                    *child_slot = Some(child);
                }

                while let Some(event) = events.recv().await {
                    match event {
                        CommandEvent::Stdout(bytes) => {
                            let line = String::from_utf8_lossy(&bytes).trim().to_string();
                            if let Some(api_base) = parse_ready_line(&line) {
                                if let Ok(mut value) = state.api_base.lock() {
                                    *value = Some(api_base.clone());
                                }
                                let _ = app_handle.emit("rivenforge-api-ready", api_base);
                            } else if !line.is_empty() {
                                state.push_log(format!("stdout: {line}"));
                            }
                        }
                        CommandEvent::Stderr(bytes) => {
                            let line = String::from_utf8_lossy(&bytes).trim().to_string();
                            if !line.is_empty() {
                                eprintln!("rivenforge-api: {line}");
                                state.push_log(format!("stderr: {line}"));
                            }
                        }
                        CommandEvent::Error(error) => {
                            eprintln!("rivenforge-api sidecar stream error: {error}");
                            state.push_log(format!("stream error: {error}"));
                        }
                        CommandEvent::Terminated(payload) => {
                            eprintln!("rivenforge-api exited: {:?}", payload.code);
                            state.push_log(format!("terminated: code={:?}", payload.code));
                            if let Ok(mut child_slot) = state.child.lock() {
                                *child_slot = None;
                            }
                            break;
                        }
                        _ => {}
                    }
                }
            });

            Ok(())
        })
        .on_window_event(move |_window, event| {
            if matches!(event, tauri::WindowEvent::Destroyed) {
                if let Ok(mut child_slot) = shutdown_state.child.lock() {
                    if let Some(child) = child_slot.take() {
                        let _ = child.kill();
                    }
                }
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running rivenforge");
}
