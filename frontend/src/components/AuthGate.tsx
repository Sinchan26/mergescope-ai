import { useEffect, useState } from "react";
import { ArrowRight, GitPullRequest, Github, LoaderCircle, SearchCode, ShieldCheck, Sparkles } from "lucide-react";
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
    <div className="ambient-backdrop" aria-hidden="true">
      <span className="ambient-orb ambient-orb-one" />
      <span className="ambient-orb ambient-orb-two" />
      <span className="ambient-grid" />
    </div>
    <section className="auth-card panel" aria-labelledby="auth-heading">
      <div className="auth-copy">
        <div className="brand"><div className="brand-mark"><SearchCode size={22} aria-hidden="true" /></div><div><strong>MergeScope</strong><span>Your code. A second perspective.</span></div></div>
        <p className="eyebrow"><Sparkles size={13} aria-hidden="true" /> AI-assisted pull request review</p>
        <h1 id="auth-heading">Review what matters.<br /><span>Ship with clarity.</span></h1>
        <p className="auth-intro">Bring a pull request, let focused agents inspect the diff, and stay in control of what gets published.</p>
        <div className="auth-features" aria-label="Product capabilities">
          <div><GitPullRequest size={18} aria-hidden="true" /><span><strong>Diff grounded</strong><small>Findings tied to changed lines</small></span></div>
          <div><ShieldCheck size={18} aria-hidden="true" /><span><strong>Human controlled</strong><small>Preview before publishing</small></span></div>
        </div>
      </div>
      <div className="auth-action">
        <div className="auth-action-heading"><span className="status-pulse" aria-hidden="true" /><span>Secure workspace access</span></div>
        <h2>Continue to your review console</h2>
        <div className="auth-assurance"><ShieldCheck size={21} aria-hidden="true" /><p>Only repositories available to your account and the installed GitHub App are in scope.</p></div>
        {error && <p className="error-banner" role="alert">{error}</p>}
        {loading ? <p className="auth-loading" role="status"><LoaderCircle size={18} className="spin" aria-hidden="true" /> Checking your session…</p> : status?.configured ? <a className="primary-button auth-login" href="/api/auth/login"><Github size={19} aria-hidden="true" />Continue with GitHub<ArrowRight size={18} aria-hidden="true" /></a> : <div className="auth-setup" role="status"><strong>One-time server setup needed</strong><p>Configure the GitHub App client ID, client secret, and encryption key. Follow <code>docs/github-login.md</code>, then restart the backend.</p></div>}
        {!loading && <button className="text-button" type="button" onClick={() => window.location.reload()}>Reload connection</button>}
        <small>No GitHub password is stored. Nothing is posted without your confirmation.</small>
      </div>
    </section>
  </main>;
}
