import { useEffect, useState } from "react";
import { LoaderCircle, SearchCode, ShieldCheck } from "lucide-react";
import App from "../App";
import { api, ApiError, setCsrfToken } from "../api";
import type { AccessibleRepository, SessionInfo } from "../api";

export function AuthGate() {
  const [session, setSession] = useState<SessionInfo | null>(null);
  const [repos, setRepos] = useState<AccessibleRepository[]>([]);
  const [status, setStatus] = useState<{ configured: boolean; install_url: string | null } | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    const reason = new URLSearchParams(window.location.search).get("auth_error");
    if (reason) {
      setError(reason === "not_allowed" ? "This GitHub account is not enabled. Ask the server operator to add your numeric GitHub user ID to ALLOWED_GITHUB_USER_IDS." : "Sign-in was cancelled or expired. Please try again.");
      window.history.replaceState(null, "", window.location.pathname);
    }
    const expired = () => {
      setCsrfToken(""); setSession(null); setRepos([]);
      setError("Your GitHub session ended. Sign in again to continue.");
    };
    window.addEventListener("mergescope:expired", expired);
    void (async () => {
      try {
        const authStatus = await api.authStatus();
        if (!active) return;
        setStatus(authStatus);
        if (!authStatus.configured) return;
        const me = await api.me();
        const repositories = await api.repositories();
        if (active) { setCsrfToken(me.csrf_token); setRepos(repositories.items); setSession(me); }
      } catch (reason) {
        if (active && !(reason instanceof ApiError && reason.status === 401)) setError(reason instanceof Error ? reason.message : "Unable to connect. Reload to retry.");
      } finally { if (active) setLoading(false); }
    })();
    return () => { active = false; window.removeEventListener("mergescope:expired", expired); };
  }, []);

  const logout = async () => {
    try { await api.logout(); setCsrfToken(""); setSession(null); setRepos([]); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Sign-out failed. Try again."); }
  };

  if (session) return <App key={session.user.id} user={session.user} repositories={repos} installUrl={status?.install_url ?? null} onLogout={() => void logout()} authError={error} />;
  return <main className="auth-page">
    <section className="auth-card panel" aria-labelledby="auth-heading">
      <div className="brand"><div className="brand-mark"><SearchCode size={22} aria-hidden="true" /></div><div><strong>MergeScope</strong><span>Your code. A second perspective.</span></div></div>
      <p className="eyebrow">A private review workspace</p>
      <h1 id="auth-heading">Sign in. Scope your repos.<br />Review with confidence.</h1>
      <p>Paste a pull request link, inspect your agents’ findings, then choose which review to publish to GitHub.</p>
      <div className="auth-assurance"><ShieldCheck size={22} aria-hidden="true" /><p>Only repositories available to your account and the GitHub App are in scope. Reviews and documents stay in your own workspace.</p></div>
      {error && <p className="error-banner" role="alert">{error}</p>}
      {loading ? <p role="status"><LoaderCircle size={18} className="spin" aria-hidden="true" /> Checking your session…</p> : status?.configured ? <a className="primary-button auth-login" href="/api/auth/login">Continue with GitHub</a> : <div className="auth-setup" role="status"><strong>One-time server setup needed</strong><p>Configure the GitHub App client ID, client secret, and encryption key. Follow <code>docs/github-login.md</code>, then restart the backend.</p></div>}
      {!loading && <button className="text-button" type="button" onClick={() => window.location.reload()}>Reload connection</button>}
      <small>No GitHub password is stored here. Nothing is posted without your confirmation.</small>
    </section>
  </main>;
}
