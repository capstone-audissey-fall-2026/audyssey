import { FormEvent, useEffect, useId, useState } from "react";
import { getGpuTools, saveGpuTools } from "../api";
import { failure } from "../lib/errors";
import type { GpuTools } from "../types";
import Icon from "./Icon";

// One tools server runs separation, filtering, grounding and generation, so one URL covers all four.
export default function GpuToolsForm({ open }: { open: boolean }) {
  const uid = useId();
  const [url, setUrl] = useState("");
  const [token, setToken] = useState("");
  const [tokenSet, setTokenSet] = useState(false);
  const [saving, setSaving] = useState(false);
  const [done, setDone] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const show = (state: GpuTools) => {
    setUrl(state.tools_url);
    setTokenSet(state.token_set);
  };

  // Reloaded each time the dialog opens, so it shows what the app uses now.
  useEffect(() => {
    if (!open) return;
    setDone(null);
    setError(null);
    getGpuTools().then(show, (e) => setError(failure("Could not load the GPU tools connection.", e, "Reopen this dialog to try again.")));
  }, [open]);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    // An empty token field keeps the saved token. The token lives only in this field, never in browser storage.
    setSaving(true);
    setDone(null);
    setError(null);
    try {
      const state = await saveGpuTools(url.trim(), token || null);
      show(state);
      setToken("");
      setDone(
        state.tools_url
          ? `Saved. New jobs use ${state.tools_url} for separation, filtering, grounding and generation.`
          : "Cleared. New jobs use the tools set in the server's environment.",
      );
    } catch (e) {
      setError(failure("Could not save the GPU tools connection.", e, "Check the URL and try again."));
    } finally {
      setSaving(false);
    }
  };

  return (
    <form className="dlg-sec" onSubmit={submit}>
      <h3>GPU tools</h3>
      <label>
        Tools server URL
        <input
          name="tools_url"
          type="url"
          inputMode="url"
          autoComplete="off"
          placeholder="https://<pod-id>-8700.proxy.runpod.net"
          value={url}
          onChange={(event) => setUrl(event.target.value)}
        />
      </label>
      <label>
        Token
        <input
          name="token"
          type="password"
          autoComplete="off"
          value={token}
          onChange={(event) => setToken(event.target.value)}
          placeholder={tokenSet ? "Saved. Leave empty to keep it." : "Not set"}
        />
      </label>
      <p className="dlg-empty">Applies to new jobs and edits. An empty URL goes back to the server's environment settings.</p>
      <div aria-live="polite" role="status" id={`${uid}-done`}>
        {done ? <p className="ok-note">{done}</p> : null}
      </div>
      {error ? (
        <p className="err" role="alert">
          <Icon name="x" />
          <span>{error}</span>
        </p>
      ) : null}
      <div className="actions">
        <button className="btn" type="submit" disabled={saving}>
          {saving ? "Saving…" : "Save"}
        </button>
      </div>
    </form>
  );
}
