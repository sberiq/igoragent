"use client";

import { FormEvent, useEffect, useState } from "react";

const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "/api";

type Configuration = {
  policy: { admin_telegram_ids: number[]; direct_access: string; group_access: string; channel_access: string; group_activation: string; allowed_direct_ids: number[]; allowed_group_ids: number[]; allowed_channel_ids: number[]; tool_permissions: Record<string, string> };
  heartbeat: { mode: string; interval_minutes: number | null; max_runs_per_hour: number | null; timezone: string };
  provider: { provider: string; endpoint: string | null; model: string; system_prompt: string; max_output_tokens: number; monthly_token_budget: number };
  memory: { enabled: boolean; writes_paused: boolean; max_items_per_scope: number; max_bytes_per_scope: number; retention_days: number; max_retrieval_items: number; max_context_tokens: number; monthly_write_token_budget: number; min_confidence: number; filter_sensitive_content: boolean };
};

type AuthState = { configured: boolean; authenticated: boolean; onboarding_completed: boolean };

function initialConfiguration(): Configuration {
  return { policy: { admin_telegram_ids: [], direct_access: "all", group_access: "whitelist", channel_access: "whitelist", group_activation: "mention_or_reply", allowed_direct_ids: [], allowed_group_ids: [], allowed_channel_ids: [], tool_permissions: { send_text: "allowed_users", send_captioned_media: "admin_only", react: "allowed_users", edit_message: "admin_only", delete_message: "admin_only", click_inline_button: "admin_only", open_deep_link: "admin_only", change_avatar: "admin_only" } }, heartbeat: { mode: "disabled", interval_minutes: null, max_runs_per_hour: null, timezone: "UTC" }, provider: { provider: "anthropic", endpoint: null, model: "claude-opus-5", system_prompt: "You are IgorAgent. Follow policy decisions and never claim an action succeeded unless its tool result confirms it.", max_output_tokens: 2048, monthly_token_budget: 2000000 }, memory: { enabled: false, writes_paused: true, max_items_per_scope: 100, max_bytes_per_scope: 262144, retention_days: 30, max_retrieval_items: 8, max_context_tokens: 1500, monthly_write_token_budget: 20000, min_confidence: 0.75, filter_sensitive_content: true } };
}

async function detail(response: Response) { const body = await response.json().catch(() => null); return body?.detail ?? "Request failed"; }

function PasswordGate({ state, onAuthenticated }: { state: AuthState; onAuthenticated: (csrf: string) => void }) {
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [setupToken, setSetupToken] = useState("");
  const [status, setStatus] = useState("");

  useEffect(() => {
    if (state.configured || typeof window === "undefined") return;
    const token = new URLSearchParams(window.location.hash.slice(1)).get("setup-token");
    if (!token) return;
    setSetupToken(token);
    window.history.replaceState(null, "", `${window.location.pathname}${window.location.search}`);
  }, [state.configured]);

  async function submit(event: FormEvent) {
    event.preventDefault(); setStatus("Checking…");
    const setup = !state.configured;
    const headers: Record<string, string> = { "Content-Type": "application/json" };
    if (setup && setupToken) headers["X-Setup-Token"] = setupToken;
    const response = await fetch(`${apiUrl}/auth/${setup ? "setup" : "login"}`, { method: "POST", credentials: "include", headers, body: JSON.stringify(setup ? { password, confirmation } : { password }) });
    if (!response.ok) return setStatus(await detail(response));
    const result = await response.json(); onAuthenticated(result.csrf_token);
  }

  return <main className="auth-page"><section className="auth-card"><p className="eyebrow">IGORAGENT CONTROL PLANE</p><h1>{state.configured ? "Sign in" : "Protect your dashboard"}</h1><p>{state.configured ? "Enter the dashboard password." : "Create a unique password before connecting AI or Telegram. It is stored only as an Argon2id hash."}</p><form onSubmit={submit}><label>Password<input required type="password" autoComplete={state.configured ? "current-password" : "new-password"} minLength={14} value={password} onChange={(e) => setPassword(e.target.value)} /></label>{!state.configured && <><label>Confirm password<input required type="password" autoComplete="new-password" minLength={14} value={confirmation} onChange={(e) => setConfirmation(e.target.value)} /></label><label>Initial setup token<input type="password" autoComplete="off" value={setupToken} onChange={(e) => setSetupToken(e.target.value)} /><span className="hint">Required only for the external IP link printed by start-ip.sh.</span></label></>}<button>{state.configured ? "Sign in" : "Create protected dashboard"}</button></form><p className="hint">{status || "Use at least 14 characters. External HTTP access should be limited to a trusted network."}</p></section></main>;
}

function Onboarding({ csrf, onCompleted }: { csrf: string; onCompleted: (configuration: Configuration) => void }) {
  const [config, setConfig] = useState(initialConfiguration());
  const [ownerId, setOwnerId] = useState(""); const [status, setStatus] = useState("");
  async function finish() {
    const owner_telegram_id = Number(ownerId); if (!Number.isSafeInteger(owner_telegram_id) || owner_telegram_id <= 0) return setStatus("Enter your Telegram numeric ID. Telegram account login follows after setup.");
    const response = await fetch(`${apiUrl}/onboarding/complete`, { method: "POST", credentials: "include", headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf }, body: JSON.stringify({ ...config, owner_telegram_id }) });
    if (!response.ok) return setStatus(await detail(response)); onCompleted(await response.json());
  }
  return <main className="onboarding"><header><div><p className="eyebrow">WELCOME TO IGORAGENT</p><h1>Set safe defaults before connecting anything.</h1></div></header><section className="wizard-card"><h2>Initial setup</h2><label>Owner Telegram numeric ID<input inputMode="numeric" value={ownerId} onChange={(e) => setOwnerId(e.target.value)} /></label><label>AI provider<input value={config.provider.provider} onChange={(e) => setConfig({ ...config, provider: { ...config.provider, provider: e.target.value } })} /></label><label>Model<input value={config.provider.model} onChange={(e) => setConfig({ ...config, provider: { ...config.provider, model: e.target.value } })} /></label><label>Group activation<select value={config.policy.group_activation} onChange={(e) => setConfig({ ...config, policy: { ...config.policy, group_activation: e.target.value } })}><option value="mention_or_reply">Mention or reply only</option><option value="all_messages">Every group message</option></select></label><label>Captioned photo posting<select value={config.policy.tool_permissions.send_captioned_media} onChange={(e) => setConfig({ ...config, policy: { ...config.policy, tool_permissions: { ...config.policy.tool_permissions, send_captioned_media: e.target.value } } })}><option value="disabled">Disabled</option><option value="admin_only">Administrators only</option><option value="allowed_users">Allowed users</option></select></label><label><input type="checkbox" checked={config.memory.enabled} onChange={(e) => setConfig({ ...config, memory: { ...config.memory, enabled: e.target.checked, writes_paused: !e.target.checked } })} /> Enable bounded memory</label><button type="button" onClick={finish}>Save initial configuration</button><p className="hint">{status || "Telegram account and LLM secrets are connected from the dashboard after this protected setup."}</p></section></main>;
}

function ControlPanel({ config, csrf, onLogout }: { config: Configuration; csrf: string; onLogout: () => void }) {
  const [configuration, setConfiguration] = useState(config); const [status, setStatus] = useState("Protected session active");
  async function save(event: FormEvent) { event.preventDefault(); const response = await fetch(`${apiUrl}/configuration`, { method: "PUT", credentials: "include", headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf }, body: JSON.stringify(configuration) }); setStatus(response.ok ? "Saved" : await detail(response)); }
  async function logout() { await fetch(`${apiUrl}/auth/logout`, { method: "POST", credentials: "include", headers: { "X-CSRF-Token": csrf } }); onLogout(); }
  return <main><header><div><p className="eyebrow">IGORAGENT CONTROL PLANE</p><h1>Agent boundaries, not blind autonomy.</h1></div><button className="secondary" type="button" onClick={logout}>Sign out</button></header><form onSubmit={save}><section><h2>Conversation</h2><label>Group activation<select value={configuration.policy.group_activation} onChange={(e) => setConfiguration({ ...configuration, policy: { ...configuration.policy, group_activation: e.target.value } })}><option value="mention_or_reply">Mention or reply only</option><option value="all_messages">Every group message</option></select></label><label>Direct messages<select value={configuration.policy.direct_access} onChange={(e) => setConfiguration({ ...configuration, policy: { ...configuration.policy, direct_access: e.target.value } })}><option value="all">All users</option><option value="whitelist">Allowlist only</option><option value="admin_only">Administrators only</option></select></label></section><section><h2>Captioned photos</h2><label>Permission<select value={configuration.policy.tool_permissions.send_captioned_media} onChange={(e) => setConfiguration({ ...configuration, policy: { ...configuration.policy, tool_permissions: { ...configuration.policy.tool_permissions, send_captioned_media: e.target.value } } })}><option value="disabled">Disabled</option><option value="admin_only">Administrators only</option><option value="allowed_users">Allowed users</option></select></label></section><section><h2>LLM budget</h2><label>Provider<input value={configuration.provider.provider} onChange={(e) => setConfiguration({ ...configuration, provider: { ...configuration.provider, provider: e.target.value } })} /></label><label>Model<input value={configuration.provider.model} onChange={(e) => setConfiguration({ ...configuration, provider: { ...configuration.provider, model: e.target.value } })} /></label><label>Output tokens<input type="number" min="256" max="16384" value={configuration.provider.max_output_tokens} onChange={(e) => setConfiguration({ ...configuration, provider: { ...configuration.provider, max_output_tokens: Number(e.target.value) } })} /></label></section><section><h2>Memory budget</h2><p>Compact facts/summaries only, never full logs.</p><label><input type="checkbox" checked={configuration.memory.enabled} onChange={(e) => setConfiguration({ ...configuration, memory: { ...configuration.memory, enabled: e.target.checked, writes_paused: !e.target.checked } })} /> Enable memory</label><label>Records per scope<input type="number" min="1" max="1000" value={configuration.memory.max_items_per_scope} onChange={(e) => setConfiguration({ ...configuration, memory: { ...configuration.memory, max_items_per_scope: Number(e.target.value) } })} /></label><label>Context token cap<input type="number" min="128" max="8000" value={configuration.memory.max_context_tokens} onChange={(e) => setConfiguration({ ...configuration, memory: { ...configuration.memory, max_context_tokens: Number(e.target.value) } })} /></label></section><section><h2>Heartbeat</h2><label>Mode<select value={configuration.heartbeat.mode} onChange={(e) => { const mode=e.target.value; setConfiguration({ ...configuration, heartbeat: { ...configuration.heartbeat, mode, interval_minutes: mode === "fixed_interval" ? 15 : null, max_runs_per_hour: mode === "random_runs_per_hour" ? 2 : null } }); }}><option value="disabled">Disabled</option><option value="fixed_interval">Fixed interval</option><option value="random_runs_per_hour">Random runs each hour</option></select></label>{configuration.heartbeat.mode === "random_runs_per_hour" && <label>Maximum runs/hour<input type="number" min="1" max="60" value={configuration.heartbeat.max_runs_per_hour ?? 2} onChange={(e) => setConfiguration({ ...configuration, heartbeat: { ...configuration.heartbeat, max_runs_per_hour: Number(e.target.value) } })} /></label>}</section><button>Save policy</button><p className="hint">{status}</p></form></main>;
}

export default function Dashboard() {
  const [auth, setAuth] = useState<AuthState | null>(null); const [csrf, setCsrf] = useState(""); const [configuration, setConfiguration] = useState<Configuration | null>(null);
  useEffect(() => { fetch(`${apiUrl}/auth/status`, { credentials: "include" }).then((r) => r.json()).then(setAuth).catch(() => setAuth({ configured: true, authenticated: false, onboarding_completed: false })); }, []);
  useEffect(() => { if (!auth?.authenticated) return; fetch(`${apiUrl}/configuration`, { credentials: "include" }).then((r) => r.ok ? r.json() : null).then(setConfiguration); }, [auth]);
  if (!auth) return <main><p>Loading protected dashboard…</p></main>;
  if (!auth.authenticated) return <PasswordGate state={auth} onAuthenticated={(token) => { setCsrf(token); setAuth({ ...auth, authenticated: true }); }} />;
  if (!auth.onboarding_completed) return <Onboarding csrf={csrf} onCompleted={(config) => { setConfiguration(config); setAuth({ ...auth, onboarding_completed: true }); }} />;
  return configuration ? <ControlPanel config={configuration} csrf={csrf} onLogout={() => { setCsrf(""); setConfiguration(null); setAuth({ ...auth, authenticated: false }); }} /> : <main><p>Loading configuration…</p></main>;
}
