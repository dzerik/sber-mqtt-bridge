/**
 * Sber MQTT Bridge — per-entity diagnostic advisor (DevTools #5).
 *
 * Compact form:
 *   * entity_id input + "Diagnose" button,
 *   * verdict badge (ok / warning / broken),
 *   * list of findings with severity + title + detail + action,
 *   * collapsible raw summary for power users who want everything.
 *
 * Designed to be pastable into a bug report — one click produces a
 * self-contained readout of everything the bridge knows about one
 * entity.
 */

/* Cache-busting: propagate our own ?v= down the import graph (lit-base.js
 * forwards it to vendor/lit.js).  Static imports would drop the query and
 * pin the browser to a stale copy of lit after an upgrade. */
const _q = new URL(import.meta.url).search;
await import(`./sber-json-block.js${_q}`);

const { LitElement, html, css } = await import(`../lit-base.js${_q}`);
const { t, ensurePanelTranslations } = await import(`../localize.js${_q}`);
const { copyText } = await import(`../utils.js${_q}`);

const VERDICT_LABEL = {
  ok: "Clean",
  warning: "Warnings",
  broken: "Broken",
};

class SberDiagnose extends LitElement {
  static get properties() {
    return {
      hass: { type: Object },
      _entityId: { type: String },
      _report: { type: Object },
      _loading: { type: Boolean },
      _error: { type: String },
      _rawOpen: { type: Boolean },
    };
  }

  constructor() {
    super();
    this._entityId = "";
    this._report = null;
    this._loading = false;
    this._error = "";
    this._rawOpen = false;
  }

  async _run() {
    if (this._loading) return;
    this._error = "";
    if (!this._entityId.trim()) {
      this._error = t(this.hass, "diagnose.enter_entity");
      return;
    }
    this._loading = true;
    try {
      const result = await this.hass.callWS({
        type: "sber_mqtt_bridge/diagnose_entity",
        entity_id: this._entityId.trim(),
      });
      this._report = result.report;
    } catch (e) {
      this._error = e.message || String(e);
    } finally {
      this._loading = false;
    }
  }

  async _copyReport() {
    if (!this._report) return;
    try {
      const ok = await copyText(JSON.stringify(this._report, null, 2));
      /* Always reassign: leaving the previous failure on screen makes a
       * later successful copy look broken. */
      this._error = ok ? "" : t(this.hass, "diagnose.copy_failed");
    } catch (e) {
      this._error = `Copy failed: ${e.message || e}`;
    }
  }

  connectedCallback() {
    super.connectedCallback();
    ensurePanelTranslations(this.hass, this);
  }

  render() {
    return html`
      <div class="section">
        <div class="section-header">
          <h2>${t(this.hass, "diagnose.title")}</h2>
        </div>
        <div class="hint">
          Runs every diagnostic rule the bridge knows against one entity — loaded, linked, enabled, acknowledged, validated, recent traces — and returns a verdict with actionable next steps.
        </div>
        <div class="form-row">
          <input
            type="text"
            aria-label="${t(this.hass, 'diagnose.entity_label')}"
            placeholder="${t(this.hass, 'diagnose.entity_placeholder')}"
            .value=${this._entityId}
            @input=${(e) => { this._entityId = e.target.value; }}
            @keydown=${(e) => { if (e.key === "Enter") this._run(); }}
          />
          <button class="btn-primary"
            ?disabled=${this._loading}
            @click=${this._run}>
            ${this._loading ? t(this.hass, "diagnose.running") : t(this.hass, "diagnose.run")}
          </button>
          ${this._report ? html`
            <button class="btn-secondary" @click=${this._copyReport}>${t(this.hass, "diagnose.copy_report")}</button>
          ` : ""}
        </div>
        ${this._error ? html`<div class="error-text">${this._error}</div>` : ""}
        ${this._report ? this._renderReport(this._report) : ""}
      </div>
    `;
  }

  _renderReport(r) {
    const verdict = r.verdict;
    return html`
      <div class="verdict verdict-${verdict}">
        <span class="verdict-badge verdict-badge-${verdict}">${VERDICT_LABEL[verdict] || verdict}</span>
        <span class="verdict-entity">${r.entity_id}</span>
      </div>
      <div class="findings">
        ${(r.findings || []).map((f) => html`
          <div class="finding finding-${f.severity}">
            <div class="finding-head">
              <span class="sev-dot sev-${f.severity}"></span>
              <span class="finding-title">${f.title}</span>
              <span class="finding-code">${f.code}</span>
            </div>
            <div class="finding-detail">${f.detail}</div>
            ${f.action ? html`<div class="finding-action"><strong>${t(this.hass, "diagnose.action")}</strong> ${f.action}</div>` : ""}
          </div>
        `)}
      </div>
      <div
        class="raw-toggle"
        role="button"
        tabindex="0"
        aria-expanded=${this._rawOpen ? "true" : "false"}
        aria-label="${t(this.hass, 'diagnose.toggle_raw')}"
        @click=${() => { this._rawOpen = !this._rawOpen; }}
        @keydown=${(e) => {
          if (e.key !== "Enter" && e.key !== " " && e.key !== "Spacebar") return;
          e.preventDefault();
          this._rawOpen = !this._rawOpen;
        }}
      >
        <span class="caret ${this._rawOpen ? "open" : ""}">&#9654;</span>
        Raw summary
      </div>
      ${this._rawOpen
        ? html`<sber-json-block .hass=${this.hass} label="${t(this.hass, 'diagnose.raw_summary')}" hide-copy .value=${r.summary}></sber-json-block>`
        : ""}
    `;
  }

  static get styles() {
    return css`
      .section {
        background: var(--card-background-color);
        border-radius: 8px;
        padding: 16px;
        margin-bottom: 16px;
      }
      .section-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }
      h2 { margin: 0; font-size: 1.1em; color: var(--primary-text-color); }
      .hint { color: var(--secondary-text-color); font-size: 0.85em; margin-bottom: 12px; }
      .form-row { display: flex; gap: 8px; align-items: center; margin-bottom: 12px; }
      input {
        flex: 1;
        padding: 6px 10px;
        border: 1px solid var(--divider-color);
        border-radius: 4px;
        background: var(--primary-background-color);
        color: var(--primary-text-color);
        font-family: monospace;
      }
      .btn-primary {
        background: var(--primary-color, #03a9f4);
        color: white;
        border: none;
        border-radius: 4px;
        padding: 6px 14px;
        cursor: pointer;
      }
      .btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }
      .btn-secondary {
        background: var(--secondary-background-color);
        color: var(--primary-text-color);
        border: 1px solid var(--divider-color);
        border-radius: 4px;
        padding: 6px 12px;
        cursor: pointer;
      }
      .error-text { color: var(--error-color, #f44336); margin-bottom: 8px; font-size: 0.9em; }
      .verdict {
        display: flex;
        align-items: center;
        gap: 12px;
        padding: 10px 14px;
        border-radius: 6px;
        margin-bottom: 12px;
      }
      .verdict-ok { background: rgba(76, 175, 80, 0.08); }
      .verdict-warning { background: rgba(255, 152, 0, 0.08); }
      .verdict-broken { background: rgba(244, 67, 54, 0.08); }
      .verdict-badge {
        padding: 3px 12px;
        border-radius: 14px;
        font-size: 0.8em;
        font-weight: 700;
        text-transform: uppercase;
      }
      .verdict-badge-ok { background: rgba(76, 175, 80, 0.2); color: var(--success-color, #4caf50); }
      .verdict-badge-warning { background: rgba(255, 152, 0, 0.2); color: var(--warning-color, #ff9800); }
      .verdict-badge-broken { background: rgba(244, 67, 54, 0.2); color: var(--error-color, #f44336); }
      .verdict-entity { font-family: monospace; color: var(--primary-text-color); }
      .findings { display: flex; flex-direction: column; gap: 8px; }
      .finding {
        border: 1px solid var(--divider-color);
        border-left-width: 3px;
        border-radius: 4px;
        padding: 10px 12px;
        background: var(--primary-background-color);
      }
      .finding-error { border-left-color: var(--error-color, #f44336); }
      .finding-warning { border-left-color: var(--warning-color, #ff9800); }
      .finding-info { border-left-color: var(--primary-color, #03a9f4); }
      .finding-ok { border-left-color: var(--success-color, #4caf50); }
      .finding-head { display: flex; align-items: center; gap: 10px; margin-bottom: 4px; }
      .sev-dot {
        width: 10px;
        height: 10px;
        border-radius: 50%;
        display: inline-block;
      }
      .sev-error { background: var(--error-color, #f44336); }
      .sev-warning { background: var(--warning-color, #ff9800); }
      .sev-info { background: var(--primary-color, #03a9f4); }
      .sev-ok { background: var(--success-color, #4caf50); }
      .finding-title { font-weight: 600; color: var(--primary-text-color); flex: 1; }
      .finding-code { font-family: monospace; font-size: 0.75em; color: var(--secondary-text-color); }
      .finding-detail { color: var(--primary-text-color); font-size: 0.9em; line-height: 1.4; }
      .finding-action {
        margin-top: 6px;
        padding: 4px 8px;
        background: var(--secondary-background-color);
        border-radius: 3px;
        font-size: 0.85em;
      }
      .raw-toggle:focus-visible,
      button:focus-visible,
      input:focus-visible {
        outline: 2px solid var(--primary-color, #03a9f4);
        outline-offset: 2px;
      }
      .raw-toggle {
        margin-top: 14px;
        color: var(--secondary-text-color);
        cursor: pointer;
        font-size: 0.85em;
        user-select: none;
      }
      .caret { display: inline-block; transition: transform 0.15s; margin-right: 4px; }
      .caret.open { transform: rotate(90deg); }
      sber-json-block { margin-top: 6px; }
    `;
  }
}

customElements.define("sber-diagnose", SberDiagnose);
