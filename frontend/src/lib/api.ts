import { invoke } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";

export type WeaponType = "primary" | "secondary" | "melee" | "archgun" | "robotic" | "stat sticks";
export type Decision = "KEEP" | "ROLL" | "REVIEW";
export type CropMode = "new_card" | "single_card" | "full";

export interface RivenStat {
  stat: string;
  value: number;
}

export interface ParsedRoll {
  positives: RivenStat[];
  negatives: RivenStat[];
  raw_lines: string[];
  dropped_sanity: string[];
  dropped_dupes: string[];
  confidence: number;
  status: "ok" | "partial" | "empty";
  issues: Array<{ code: string; message: string; raw_line: string | null }>;
}

export interface RuleResult {
  accept: boolean;
  profile_matched: string | null;
  details: string;
  decision: Decision;
  traces: Array<{ code: string; message: string; matched: boolean }>;
}

export interface RollProfile {
  name: string;
  desired_positives: string[];
  min_positives_required: number;
  acceptable_negatives: string[];
  rejected_negatives?: string[];
  required_negatives?: string[];
  min_negatives_required?: number;
  schema_version?: number;
}

export interface UserConfig {
  weapon: string;
  weapon_type: WeaponType;
  profiles: RollProfile[];
  roll_limit: number;
  rag_threshold: number;
  animation_wait: number;
  button_coords?: Record<string, number[]>;
}

export interface WeaponEntry {
  weapon: string;
  weapon_type: WeaponType;
  positives: string[];
  negatives: string[];
  notes?: string;
}

export interface AnalyzeResponse {
  parse: ParsedRoll;
  decision: RuleResult;
  confidence: number;
  capture_path: "mss" | "dxgi" | "mss(dark)";
  brightness: number;
  review_reasons: string[];
}

export interface CaptureStatus {
  available: boolean;
  found: boolean;
  visible: boolean;
  minimized: boolean;
  foreground: boolean;
  rect: [number, number, number, number] | null;
  capture_backends: Record<string, boolean>;
  notes: string[];
}

export interface RagStatus {
  ready: boolean;
  entries: number;
}

export interface RollEvent {
  kind: "roll";
  session_id: string;
  roll_num: number;
  parsed: ParsedRoll;
  rule_result: RuleResult;
  rag_result: Record<string, unknown>;
  accepted: boolean;
}

export type ApiEvent =
  | RollEvent
  | { kind: "done"; session_id?: string; reason: string }
  | { kind: "error"; session_id?: string; message: string }
  | { kind: "ingest"; job_id: string; current: number; total: number }
  | { kind: "ingest_done"; job_id: string; total: number };

/**
 * The bundled sidecar listens on this fixed port (see api_sidecar.py
 * DEFAULT_PORT). Hardcoding it on both sides means:
 *   - No localStorage accumulation of dead random ports
 *   - No bootstrap race between the Rust READY emit and the React mount
 *   - Reconnect is just "retry the same URL" — no port discovery needed
 *
 * Users can still override the URL via Settings → API base (stored under
 * `API_BASE_OVERRIDE_KEY`); empty/missing override falls through to the
 * default. The old `rivenforge.apiBase` key is migrated/cleared on load.
 */
export const DEFAULT_BUNDLED_API_BASE = "http://127.0.0.1:47321";

const LEGACY_API_BASE_KEY = "rivenforge.apiBase";
const API_BASE_OVERRIDE_KEY = "rivenforge.apiBaseOverride";

// One-time cleanup of the legacy key that accumulated stale random ports.
try {
  localStorage.removeItem(LEGACY_API_BASE_KEY);
} catch {
  // localStorage unavailable (private mode etc.) — fine.
}

export function getApiBase(): string {
  const override = (localStorage.getItem(API_BASE_OVERRIDE_KEY) || "").trim();
  if (override) return override.replace(/\/$/, "");
  return (import.meta.env.VITE_API_BASE as string | undefined) || DEFAULT_BUNDLED_API_BASE;
}

export function setApiBaseOverride(value: string): void {
  const trimmed = value.trim().replace(/\/$/, "");
  if (trimmed) {
    localStorage.setItem(API_BASE_OVERRIDE_KEY, trimmed);
  } else {
    localStorage.removeItem(API_BASE_OVERRIDE_KEY);
  }
}

/** @deprecated kept for old call sites — use setApiBaseOverride. */
export const setApiBase = setApiBaseOverride;

/**
 * Ask Tauri for the sidecar's port. Returns the URL if Tauri reports it
 * ready, null in dev mode / outside Tauri. Updates the override is NOT
 * called here — the fixed default always works unless the user picked a
 * custom port via --port, in which case Tauri reports that explicitly.
 */
export async function initBundledApiBase(): Promise<string | null> {
  try {
    const apiBase = await invoke<string | null>("get_sidecar_api_base");
    return apiBase || null;
  } catch {
    return null;
  }
}

export async function subscribeBundledApiReady(onReady: (apiBase: string) => void): Promise<UnlistenFn | null> {
  try {
    return await listen<string>("rivenforge-api-ready", (event) => {
      onReady(event.payload);
    });
  } catch {
    return null;
  }
}

/**
 * Subscribe to the global emergency-stop hotkey (Ctrl+Shift+Q by default,
 * registered in src-tauri/main.rs). Fires while Warframe has focus — the
 * UI Stop button is unreachable once the bot grabs the mouse.
 *
 * Returns an unlisten function (null when not running inside Tauri, e.g.
 * vite dev mode). The handler receives the human-readable hotkey label
 * Rust sent as the event payload so the UI can confirm what's bound.
 */
export async function subscribeHotkeyStop(onStop: (label: string) => void): Promise<UnlistenFn | null> {
  try {
    return await listen<string>("rivenforge-hotkey-stop", (event) => {
      onStop(event.payload);
    });
  } catch {
    return null;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${getApiBase()}${path}`, init);
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `${response.status} ${response.statusText}`);
  }
  return (await response.json()) as T;
}

export const api = {
  health: () => request<{ ready: boolean; capture_path: string }>("/health"),
  diagnostics: async () => {
    const response = await fetch(`${getApiBase()}/diagnostics/export`);
    if (!response.ok) {
      const text = await response.text();
      throw new Error(text || `${response.status} ${response.statusText}`);
    }
    return response.blob();
  },
  config: () => request<UserConfig>("/config"),
  saveConfig: (cfg: UserConfig) =>
    request<{ saved: boolean }>("/config", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(cfg)
    }),
  stats: () => request<string[]>("/stats"),
  weapons: (type?: WeaponType) => request<WeaponEntry[]>(`/weapons${type ? `?type=${encodeURIComponent(type)}` : ""}`),
  suggestedProfiles: (weapon: string) => request<RollProfile[]>(`/weapons/${encodeURIComponent(weapon)}/suggested`),
  analyze: (file: File, cropMode: CropMode, manualOcrText: string) => {
    const body = new FormData();
    body.append("screenshot", file);
    body.append("crop_mode", cropMode);
    body.append("manual_ocr_text", manualOcrText);
    return request<AnalyzeResponse>("/analyze", { method: "POST", body });
  },
  captureStatus: () => request<CaptureStatus>("/capture/status"),
  analyzeLiveCapture: (cropMode: CropMode) => {
    const body = new FormData();
    body.append("crop_mode", cropMode);
    body.append("monitor_index", "0");
    return request<AnalyzeResponse>("/capture/analyze", { method: "POST", body });
  },
  startRoll: (cfg: UserConfig) =>
    request<{ session_id: string }>("/roll/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        weapon: cfg.weapon,
        weapon_type: cfg.weapon_type,
        profiles: cfg.profiles,
        roll_limit: cfg.roll_limit,
        rag_threshold: cfg.rag_threshold,
        animation_wait: cfg.animation_wait
      })
    }),
  stopRoll: () => request<{ stopped: boolean }>("/roll/stop", { method: "POST" }),
  ragStatus: () => request<RagStatus>("/rag/status"),
  rebuildRag: () => request<{ job_id: string }>("/rag/rebuild", { method: "POST" })
};

export type EventSocketStatus = "connecting" | "open" | "closed";

export interface EventSocketHandle {
  /** Close the socket and stop reconnecting. */
  close: () => void;
  /** Return current status (latest known). */
  status: () => EventSocketStatus;
}

/**
 * Open a WebSocket to /events that reconnects with exponential backoff
 * (capped at 8s) until `close()` is called. Calls `onEvent` per message,
 * `onStatus` whenever the connection state changes.
 *
 * The old version was a bare `WebSocket` with no onclose/onerror. When the
 * sidecar dropped the connection (route navigation, sidecar restart,
 * Windows WinError 10054), the React side silently lost its event feed
 * forever and the UI looked unresponsive — that was the user-visible "app
 * doesn't work" symptom.
 */
export function createEventSocket(
  onEvent: (event: ApiEvent) => void,
  onStatus?: (status: EventSocketStatus) => void,
): EventSocketHandle {
  let ws: WebSocket | null = null;
  let closed = false;
  let attempt = 0;
  let timer: ReturnType<typeof setTimeout> | null = null;
  let status: EventSocketStatus = "connecting";

  const setStatus = (next: EventSocketStatus) => {
    status = next;
    onStatus?.(next);
  };

  const connect = () => {
    if (closed) return;
    setStatus("connecting");
    const url = new URL(getApiBase());
    url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
    url.pathname = "/events";
    const socket = new WebSocket(url);
    ws = socket;
    socket.onopen = () => {
      attempt = 0;
      setStatus("open");
    };
    socket.onmessage = (message) => {
      try {
        onEvent(JSON.parse(message.data) as ApiEvent);
      } catch {
        // Malformed event — drop it. Don't crash the socket.
      }
    };
    socket.onerror = () => {
      // The 'close' handler will fire next; let it drive reconnection.
    };
    socket.onclose = () => {
      ws = null;
      setStatus("closed");
      if (closed) return;
      // Exponential backoff: 250ms, 500, 1000, 2000, 4000, 8000 (cap).
      const delay = Math.min(8000, 250 * 2 ** attempt);
      attempt += 1;
      timer = setTimeout(connect, delay);
    };
  };

  connect();

  return {
    close: () => {
      closed = true;
      if (timer) {
        clearTimeout(timer);
        timer = null;
      }
      if (ws) {
        try {
          ws.close();
        } catch {
          // ignore
        }
      }
    },
    status: () => status,
  };
}
