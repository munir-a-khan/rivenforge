import {
  Activity,
  AlertTriangle,
  BarChart3,
  Bug,
  Circle,
  Download,
  FileImage,
  Play,
  Save,
  Settings,
  ShieldCheck,
  SlidersHorizontal,
  Square,
  Wand2
} from "lucide-react";
import { ChangeEvent, DragEvent, useEffect, useMemo, useRef, useState } from "react";

import {
  AnalyzeResponse,
  ApiEvent,
  CropMode,
  Decision,
  EventSocketStatus,
  RollEvent,
  RollProfile,
  UserConfig,
  WeaponEntry,
  WeaponType,
  api,
  createEventSocket,
  getApiBase,
  initBundledApiBase,
  setApiBaseOverride,
  subscribeBundledApiReady,
  subscribeHotkeyStop
} from "./lib/api";

type RouteId = "rolls" | "profiles" | "analyze" | "settings";

const weaponTypes: WeaponType[] = ["primary", "secondary", "melee", "archgun", "robotic", "stat sticks"];

/**
 * Fallback stat list used only until /stats responds. Kept narrow on
 * purpose — the real source of truth is `data/stat_aliases.json` on the
 * backend, served by `api.stats()`. Same list serves BOTH positives and
 * negatives because niche builds want unusual choices in either column.
 */
const STAT_OPTIONS_FALLBACK = [
  "Critical Chance",
  "Critical Damage",
  "Damage",
  "Multishot",
  "Attack Speed",
  "Fire Rate",
  "Reload Speed",
  "Range",
  "Status Chance",
  "Status Duration",
  "Slide Critical Chance",
  "Initial Combo",
  "Combo Duration",
  "Heavy Attack Efficiency",
  "Finisher Damage",
  "Melee Damage",
  "Slam Damage",
  "Elemental Damage",
  "Electricity",
  "Cold",
  "Heat",
  "Toxin",
  "Impact",
  "Puncture",
  "Slash",
  "Recoil",
  "Zoom",
  "Projectile Flight Speed",
  "Punch Through",
  "Magazine Capacity",
  "Ammo Maximum",
  "Damage to Corpus",
  "Damage to Grineer",
  "Damage to Infested"
];

const emptyConfig: UserConfig = {
  weapon: "",
  weapon_type: "melee",
  profiles: [],
  roll_limit: 25,
  rag_threshold: 0,
  animation_wait: 2.5
};
const ONBOARDING_KEY = "rivenforge.onboardingComplete.v1";

function App() {
  const [route, setRoute] = useState<RouteId>("rolls");
  const [apiBaseInput, setApiBaseInput] = useState(getApiBase());
  const [apiStatus, setApiStatus] = useState<"checking" | "online" | "offline">("checking");
  const [wsStatus, setWsStatus] = useState<EventSocketStatus>("connecting");
  const [config, setConfig] = useState<UserConfig>(emptyConfig);
  const [events, setEvents] = useState<ApiEvent[]>([]);
  const [rolls, setRolls] = useState<RollEvent[]>([]);
  const [running, setRunning] = useState(false);
  const [message, setMessage] = useState("");
  const [statOptions, setStatOptions] = useState<string[]>(STAT_OPTIONS_FALLBACK);
  const [showOnboarding, setShowOnboarding] = useState(() => localStorage.getItem(ONBOARDING_KEY) !== "true");

  async function refresh() {
    setApiStatus("checking");
    try {
      await api.health();
      const cfg = await api.config();
      setConfig({ ...emptyConfig, ...cfg, profiles: cfg.profiles || [] });
      setApiStatus("online");
    } catch (error) {
      setApiStatus("offline");
      setMessage(error instanceof Error ? error.message : "API unavailable");
    }
  }

  // Bootstrap: the sidecar listens on a fixed port (47321), so first try
  // /health directly. If Tauri also reports a port via the ready event
  // (e.g. user ran the sidecar with --port 0), we adopt that as an
  // override. No more 60-poll race.
  useEffect(() => {
    let cancelled = false;
    let unlisten: (() => void) | null = null;

    async function bootstrap() {
      unlisten = await subscribeBundledApiReady((apiBase) => {
        if (cancelled) return;
        const fromTauri = apiBase.replace(/\/$/, "");
        if (fromTauri !== getApiBase()) {
          setApiBaseOverride(fromTauri);
          setApiBaseInput(fromTauri);
        }
        refresh();
      });

      // If Tauri already had the URL cached (event fired before we mounted),
      // pick it up. Otherwise the fixed default works and refresh() succeeds
      // as soon as the sidecar binds.
      const cached = await initBundledApiBase();
      if (cached && !cancelled) {
        const trimmed = cached.replace(/\/$/, "");
        if (trimmed !== getApiBase()) {
          setApiBaseOverride(trimmed);
          setApiBaseInput(trimmed);
        }
      }
      // Always probe. Will retry every 1s up to ~30s while the sidecar
      // boots; healthy probe flips status to online and unblocks the UI.
      for (let i = 0; i < 30 && !cancelled; i += 1) {
        try {
          await api.health();
          await refresh();
          return;
        } catch {
          await new Promise((r) => window.setTimeout(r, 1000));
        }
      }
      if (!cancelled) refresh(); // final attempt — leaves the offline toast
    }

    bootstrap();
    return () => {
      cancelled = true;
      unlisten?.();
    };
  }, []);

  // Pull the canonical stat list once the API is online. Falls back to
  // STAT_OPTIONS_FALLBACK forever if /stats can't be reached — better than
  // showing an empty picker.
  useEffect(() => {
    if (apiStatus !== "online") return;
    let cancelled = false;
    api.stats().then((stats) => {
      if (cancelled || !Array.isArray(stats) || stats.length === 0) return;
      setStatOptions(stats);
    }).catch(() => {
      // keep fallback
    });
    return () => { cancelled = true; };
  }, [apiStatus]);

  // Global emergency-stop hotkey (Ctrl+Shift+Q, registered in main.rs).
  // Fires while Warframe has focus — the on-screen Stop button is
  // unreachable once the bot grabs the mouse. We always call stopRoll
  // regardless of `running` state because the server treats an idle stop
  // as a no-op and idempotency beats us guessing what the bot is doing.
  useEffect(() => {
    let unlisten: (() => void) | null = null;
    (async () => {
      unlisten = await subscribeHotkeyStop((label) => {
        api.stopRoll().catch(() => undefined);
        setRunning(false);
        setMessage(`Stopped by ${label}.`);
      });
    })();
    return () => { unlisten?.(); };
  }, []);

  // Event WebSocket: opens once the API is reachable and survives
  // sidecar restarts via the reconnecting socket helper.
  useEffect(() => {
    if (apiStatus !== "online") return undefined;
    const handle = createEventSocket(
      (event) => {
        setEvents((prev) => [event, ...prev].slice(0, 80));
        if (event.kind === "roll") setRolls((prev) => [event, ...prev]);
        if (event.kind === "done" || event.kind === "error") setRunning(false);
      },
      (status) => setWsStatus(status),
    );
    return () => handle.close();
  }, [apiStatus]);

  async function saveConfig(next = config) {
    await api.saveConfig(next);
    setConfig(next);
    setMessage("Profile settings saved.");
  }

  async function startRolling() {
    try {
      const response = await api.startRoll(config);
      setRunning(true);
      setMessage(`Rolling session started: ${response.session_id}`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Failed to start rolling.");
    }
  }

  async function stopRolling() {
    await api.stopRoll();
    setRunning(false);
    setMessage("Stop requested.");
  }

  async function exportDiagnostics() {
    try {
      const blob = await api.diagnostics();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = "rivenforge-diagnostics.zip";
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
      setMessage("Diagnostic bundle exported.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Failed to export diagnostics.");
    }
  }

  function dismissOnboarding() {
    localStorage.setItem(ONBOARDING_KEY, "true");
    setShowOnboarding(false);
  }

  async function reconnectApi() {
    const bundledApiBase = await initBundledApiBase();
    if (bundledApiBase) {
      const trimmed = bundledApiBase.replace(/\/$/, "");
      if (trimmed !== getApiBase()) {
        setApiBaseOverride(trimmed);
        setApiBaseInput(trimmed);
      }
    }
    await refresh();
  }

  async function checkRagStatus() {
    try {
      return await api.ragStatus();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Failed to check RAG status.");
      throw error;
    }
  }

  async function rebuildRagIndex() {
    try {
      await api.rebuildRag();
      setMessage("RAG rebuild started.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Failed to rebuild RAG index.");
    }
  }

  const activeProfileCount = config.profiles.length;
  const acceptedCount = rolls.filter((roll) => roll.accepted).length;
  const bestScore = useMemo(() => {
    const scores = rolls.map((roll) => Number(roll.rag_result?.new_score ?? 0));
    return scores.length ? Math.max(...scores) : 0;
  }, [rolls]);

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">RF</div>
          <div>
            <strong>rivenforge</strong>
            <span>local analyzer</span>
          </div>
        </div>
        <nav>
          <NavButton active={route === "rolls"} icon={<BarChart3 />} label="Roll Log" onClick={() => setRoute("rolls")} />
          <NavButton active={route === "profiles"} icon={<SlidersHorizontal />} label="Profiles" onClick={() => setRoute("profiles")} />
          <NavButton active={route === "analyze"} icon={<FileImage />} label="Manual Analyze" onClick={() => setRoute("analyze")} />
          <NavButton active={route === "settings"} icon={<Settings />} label="Settings" onClick={() => setRoute("settings")} />
        </nav>
        <div
          className={`api-pill ${apiStatus}`}
          title={`API base: ${getApiBase()}  ·  events: ${wsStatus}`}
        >
          <Circle size={10} fill="currentColor" />
          <span>
            {apiStatus === "online"
              ? wsStatus === "open"
                ? "API online"
                : wsStatus === "connecting"
                ? "API · events…"
                : "API · events offline"
              : apiStatus === "offline"
              ? "API offline"
              : "checking API"}
          </span>
        </div>
      </aside>

      <main className="main">
        <header className="topbar">
          <div>
            <p className="eyebrow">{config.weapon_type}</p>
            <h1>{config.weapon || "Select a weapon"}</h1>
          </div>
          <div className="top-actions">
            <Kpi label="rolls" value={String(rolls.length)} />
            <Kpi label="profiles" value={String(activeProfileCount)} />
            <Kpi label="accepted" value={String(acceptedCount)} />
            <Kpi label="best" value={bestScore ? bestScore.toFixed(0) : "-"} />
          </div>
        </header>

        {message && <div className="toast">{message}</div>}

        {route === "rolls" && <RollLog rolls={rolls} events={events} />}
        {route === "profiles" && <Profiles config={config} setConfig={setConfig} saveConfig={saveConfig} statOptions={statOptions} />}
        {route === "analyze" && <ManualAnalyze />}
        {route === "settings" && (
          <SettingsPage
            apiBaseInput={apiBaseInput}
            setApiBaseInput={setApiBaseInput}
            applyApiBase={() => {
              setApiBaseOverride(apiBaseInput);
              refresh();
            }}
            resetApiBase={() => {
              setApiBaseOverride("");
              setApiBaseInput(getApiBase());
              refresh();
            }}
            reconnect={reconnectApi}
            exportDiagnostics={exportDiagnostics}
            checkRagStatus={checkRagStatus}
            rebuildRagIndex={rebuildRagIndex}
          />
        )}
      </main>

      <footer className="footer">
        <button className="primary-action" onClick={running ? stopRolling : startRolling}>
          {running ? <Square size={18} /> : <Play size={18} />}
          {running ? "Stop Rolling" : "Start Rolling"}
        </button>
        <span className="keycap">Ctrl + Shift + Q</span>
        <span className="footer-note">Manual analysis and profiles work without starting automation.</span>
      </footer>

      {showOnboarding && <OnboardingModal onClose={dismissOnboarding} />}
    </div>
  );
}

function NavButton({ active, icon, label, onClick }: { active: boolean; icon: JSX.Element; label: string; onClick: () => void }) {
  return (
    <button className={`nav-button ${active ? "active" : ""}`} onClick={onClick}>
      {icon}
      <span>{label}</span>
    </button>
  );
}

function Kpi({ label, value }: { label: string; value: string }) {
  return (
    <div className="kpi">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function RollLog({ rolls, events }: { rolls: RollEvent[]; events: ApiEvent[] }) {
  return (
    <section className="page-grid">
      <div className="panel wide">
        <PanelTitle icon={<Activity />} title="Roll Log" />
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>#</th>
                <th>POS 1</th>
                <th>POS 2</th>
                <th>POS 3</th>
                <th>NEG</th>
                <th>Profile</th>
                <th>Score</th>
                <th>Decision</th>
              </tr>
            </thead>
            <tbody>
              {rolls.length === 0 ? (
                <tr>
                  <td colSpan={8} className="empty-row">No rolls yet.</td>
                </tr>
              ) : (
                rolls.map((roll) => {
                  const positives = roll.parsed.positives;
                  const neg = roll.parsed.negatives[0]?.stat || "-";
                  return (
                    <tr key={`${roll.session_id}-${roll.roll_num}`}>
                      <td>{roll.roll_num}</td>
                      <td>{positives[0]?.stat || "-"}</td>
                      <td>{positives[1]?.stat || "-"}</td>
                      <td>{positives[2]?.stat || "-"}</td>
                      <td>{neg}</td>
                      <td>{roll.rule_result.profile_matched || "-"}</td>
                      <td>{String(roll.rag_result?.new_score ?? "-")}</td>
                      <td><DecisionPill decision={roll.rule_result.decision} /></td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>
      <DebugDrawer events={events} />
    </section>
  );
}

function DecisionPill({ decision }: { decision: Decision }) {
  return <span className={`decision ${decision.toLowerCase()}`}>{decision}</span>;
}

function Profiles({
  config,
  setConfig,
  saveConfig,
  statOptions
}: {
  config: UserConfig;
  setConfig: (cfg: UserConfig) => void;
  saveConfig: (cfg?: UserConfig) => Promise<void>;
  statOptions: string[];
}) {
  const [weapons, setWeapons] = useState<WeaponEntry[]>([]);

  useEffect(() => {
    api.weapons(config.weapon_type).then(setWeapons).catch(() => setWeapons([]));
  }, [config.weapon_type]);

  function updateProfile(index: number, profile: RollProfile) {
    const next = { ...config, profiles: config.profiles.map((p, i) => (i === index ? profile : p)) };
    setConfig(next);
  }

  return (
    <section className="page-grid">
      <div className="panel">
        <PanelTitle icon={<Wand2 />} title="Weapon" />
        <label>Type</label>
        <select value={config.weapon_type} onChange={(e) => setConfig({ ...config, weapon_type: e.target.value as WeaponType })}>
          {weaponTypes.map((type) => <option key={type}>{type}</option>)}
        </select>
        <label>Weapon</label>
        <input
          list="weapon-list"
          value={config.weapon}
          onChange={(e) => setConfig({ ...config, weapon: e.target.value })}
          placeholder="Search weapon"
        />
        <datalist id="weapon-list">
          {weapons.map((weapon) => <option key={weapon.weapon} value={weapon.weapon} />)}
        </datalist>
        <button
          className="secondary"
          onClick={async () => {
            const profiles = await api.suggestedProfiles(config.weapon);
            setConfig({ ...config, profiles });
          }}
        >
          Load Suggested
        </button>
      </div>

      <div className="panel wide">
        <PanelTitle icon={<SlidersHorizontal />} title="Profiles" />
        <div className="profile-list">
          {config.profiles.map((profile, index) => (
            <ProfileCard
              key={`${profile.name}-${index}`}
              profile={profile}
              statOptions={statOptions}
              onChange={(next) => updateProfile(index, next)}
              onDelete={() => setConfig({ ...config, profiles: config.profiles.filter((_, i) => i !== index) })}
            />
          ))}
        </div>
        <div className="row">
          <button
            className="secondary"
            onClick={() => setConfig({
              ...config,
              profiles: [
                ...config.profiles,
                { name: "New Profile", desired_positives: ["Critical Damage", "Range"], min_positives_required: 2, acceptable_negatives: [] }
              ]
            })}
          >
            Add Profile
          </button>
          <button className="secondary" onClick={() => saveConfig()}>
            <Save size={16} />
            Save Profiles
          </button>
        </div>
      </div>

      <div className="panel">
        <PanelTitle icon={<Settings />} title="Rolling" />
        <label>Roll limit</label>
        <input type="number" value={config.roll_limit} onChange={(e) => setConfig({ ...config, roll_limit: Number(e.target.value) })} />
        <label>RAG threshold</label>
        <input type="number" step="0.05" value={config.rag_threshold} onChange={(e) => setConfig({ ...config, rag_threshold: Number(e.target.value) })} />
        <label>Animation wait</label>
        <input type="number" step="0.25" value={config.animation_wait} onChange={(e) => setConfig({ ...config, animation_wait: Number(e.target.value) })} />
      </div>
    </section>
  );
}

function ProfileCard({
  profile,
  statOptions,
  onChange,
  onDelete
}: {
  profile: RollProfile;
  statOptions: string[];
  onChange: (profile: RollProfile) => void;
  onDelete: () => void;
}) {
  return (
    <div className="profile-card">
      <div className="row">
        <input value={profile.name} onChange={(e) => onChange({ ...profile, name: e.target.value })} />
        <button className="icon-button" onClick={onDelete}>Delete</button>
      </div>
      <label>Desired positives</label>
      <ChipEditor
        statOptions={statOptions}
        values={profile.desired_positives}
        onChange={(values) => onChange({ ...profile, desired_positives: values })}
      />
      <label>Acceptable negatives</label>
      <ChipEditor
        statOptions={statOptions}
        values={profile.acceptable_negatives}
        onChange={(values) => onChange({ ...profile, acceptable_negatives: values })}
      />
      <label>Minimum positives</label>
      <input
        type="number"
        min={1}
        max={3}
        value={profile.min_positives_required}
        onChange={(e) => onChange({ ...profile, min_positives_required: Number(e.target.value) })}
      />
    </div>
  );
}

function ChipEditor({
  statOptions,
  values,
  onChange
}: {
  statOptions: string[];
  values: string[];
  onChange: (values: string[]) => void;
}) {
  return (
    <div className="chips">
      {statOptions.map((stat) => {
        const active = values.includes(stat);
        return (
          <button
            key={stat}
            className={`chip ${active ? "active" : ""}`}
            onClick={() => onChange(active ? values.filter((v) => v !== stat) : [...values, stat])}
          >
            {stat}
          </button>
        );
      })}
    </div>
  );
}

function ManualAnalyze() {
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState("");
  const [cropMode, setCropMode] = useState<CropMode>("new_card");
  const [manualOcr, setManualOcr] = useState("");
  const [result, setResult] = useState<AnalyzeResponse | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  function acceptFile(next: File) {
    setFile(next);
    setPreview(URL.createObjectURL(next));
  }

  function onDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    const next = event.dataTransfer.files[0];
    if (next) acceptFile(next);
  }

  async function analyze() {
    if (!file) return;
    setResult(await api.analyze(file, cropMode, manualOcr));
  }

  async function pasteImage() {
    const items = await navigator.clipboard.read();
    for (const item of items) {
      const type = item.types.find((candidate) => candidate.startsWith("image/"));
      if (type) {
        const blob = await item.getType(type);
        acceptFile(new File([blob], "clipboard.png", { type }));
        return;
      }
    }
  }

  return (
    <section className="page-grid">
      <div className="panel">
        <PanelTitle icon={<FileImage />} title="Manual Analyze" />
        <div className="dropzone" onDrop={onDrop} onDragOver={(event) => event.preventDefault()} onClick={() => inputRef.current?.click()}>
          {preview ? <img src={preview} alt="Riven screenshot preview" /> : <span>Drop or choose screenshot</span>}
        </div>
        <input ref={inputRef} type="file" accept="image/*" hidden onChange={(e: ChangeEvent<HTMLInputElement>) => e.target.files?.[0] && acceptFile(e.target.files[0])} />
        <div className="row">
          <button className="secondary" onClick={() => inputRef.current?.click()}>Choose File</button>
          <button className="secondary" onClick={pasteImage}>Paste Image</button>
        </div>
        <label>Crop mode</label>
        <select value={cropMode} onChange={(e) => setCropMode(e.target.value as CropMode)}>
          <option value="new_card">New card</option>
          <option value="single_card">Single card</option>
          <option value="full">Full screen</option>
        </select>
        <p className="hint">New card targets the right-side comparison roll. Single card targets the centered card. Full screen skips cropping for debugging.</p>
        <label>Manual OCR lines</label>
        <textarea value={manualOcr} onChange={(e) => setManualOcr(e.target.value)} placeholder="+120% Critical Damage&#10;+80% Range&#10;-30% Impact" />
        <button className="primary-action compact" disabled={!file} onClick={analyze}>Analyze</button>
      </div>

      <div className="panel wide">
        <PanelTitle icon={<ShieldCheck />} title="Decision" />
        {result ? (
          <div className="analysis-result">
            <DecisionPill decision={result.decision.decision} />
            <p>{result.decision.details}</p>
            <div className="stat-grid">
              {result.parse.positives.map((stat) => <StatTile key={`${stat.stat}-${stat.value}`} stat={stat} />)}
              {result.parse.negatives.map((stat) => <StatTile key={`${stat.stat}-${stat.value}`} stat={stat} negative />)}
            </div>
            <DebugText result={result} />
          </div>
        ) : (
          <p className="empty-row">Analyze a screenshot to see parser output and rule trace.</p>
        )}
      </div>
    </section>
  );
}

function StatTile({ stat, negative }: { stat: { stat: string; value: number }; negative?: boolean }) {
  return (
    <div className={`stat-tile ${negative ? "negative" : ""}`}>
      <strong>{negative ? stat.value.toFixed(1) : `+${stat.value.toFixed(1)}`}</strong>
      <span>{stat.stat}</span>
    </div>
  );
}

function DebugText({ result }: { result: AnalyzeResponse }) {
  return (
    <pre className="debug-text">
{JSON.stringify({
  confidence: result.confidence,
  status: result.parse.status,
  review_reasons: result.review_reasons,
  traces: result.decision.traces
}, null, 2)}
    </pre>
  );
}

function SettingsPage({
  apiBaseInput,
  setApiBaseInput,
  applyApiBase,
  resetApiBase,
  reconnect,
  exportDiagnostics,
  checkRagStatus,
  rebuildRagIndex
}: {
  apiBaseInput: string;
  setApiBaseInput: (value: string) => void;
  applyApiBase: () => void;
  resetApiBase: () => void;
  reconnect: () => Promise<void>;
  exportDiagnostics: () => Promise<void>;
  checkRagStatus: () => Promise<{ ready: boolean; entries: number }>;
  rebuildRagIndex: () => Promise<void>;
}) {
  const [rag, setRag] = useState<{ ready: boolean; entries: number } | null>(null);
  return (
    <section className="page-grid">
      <div className="panel">
        <PanelTitle icon={<Settings />} title="API" />
        <label>API base URL</label>
        <input value={apiBaseInput} onChange={(e) => setApiBaseInput(e.target.value)} />
        <p className="hint">
          Bundled mode uses <code>http://127.0.0.1:47321</code>. Override only
          when running the sidecar manually on a different port.
        </p>
        <div className="row">
          <button className="secondary" onClick={applyApiBase}>Apply Override</button>
          <button className="secondary" onClick={resetApiBase}>Use Default</button>
          <button className="secondary" onClick={reconnect}>Reconnect</button>
        </div>
      </div>
      <div className="panel">
        <PanelTitle icon={<Bug />} title="RAG Index" />
        <p>{rag ? `${rag.ready ? "Ready" : "Not ready"} - ${rag.entries} entries` : "Status unknown"}</p>
        <div className="row">
          <button className="secondary" onClick={async () => setRag(await checkRagStatus())}>Check</button>
          <button className="secondary" onClick={rebuildRagIndex}>Rebuild</button>
        </div>
      </div>
      <div className="panel wide">
        <PanelTitle icon={<AlertTriangle />} title="Safety" />
        <p>Automation remains optional. Manual analysis, profiles, and logs can be used without clicking in-game.</p>
        <div className="row">
          <button className="secondary" onClick={exportDiagnostics}>
            <Download size={16} />
            Export Diagnostics
          </button>
        </div>
      </div>
    </section>
  );
}

function OnboardingModal({ onClose }: { onClose: () => void }) {
  return (
    <div className="modal-backdrop">
      <div className="modal">
        <div className="panel-title">
          <ShieldCheck />
          <h2>First Run</h2>
        </div>
        <div className="onboarding-grid">
          <div>
            <strong>Manual first</strong>
            <p>Use Manual Analyze to test screenshots before any rolling session.</p>
          </div>
          <div>
            <strong>Profiles decide</strong>
            <p>KEEP only happens when your selected rule profile matches structured riven stats.</p>
          </div>
          <div>
            <strong>Review on uncertainty</strong>
            <p>Partial or low-confidence OCR returns REVIEW and will not choose ROLL for you.</p>
          </div>
          <div>
            <strong>Local diagnostics</strong>
            <p>Exports stay on this computer unless you choose to share the zip.</p>
          </div>
        </div>
        <button className="primary-action compact" onClick={onClose}>Continue</button>
      </div>
    </div>
  );
}

function DebugDrawer({ events }: { events: ApiEvent[] }) {
  return (
    <div className="panel">
      <PanelTitle icon={<Bug />} title="Event Feed" />
      <pre className="debug-text">{events.length ? JSON.stringify(events.slice(0, 12), null, 2) : "No events yet."}</pre>
    </div>
  );
}

function PanelTitle({ icon, title }: { icon: JSX.Element; title: string }) {
  return (
    <div className="panel-title">
      {icon}
      <h2>{title}</h2>
    </div>
  );
}

export default App;
