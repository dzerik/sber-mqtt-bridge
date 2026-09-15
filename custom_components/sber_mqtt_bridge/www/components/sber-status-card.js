/**
 * Sber MQTT Bridge — Connection status card component.
 *
 * Displays MQTT connection lifecycle phase with a coloured dot indicator
 * and descriptive text. Phases: starting, connecting, awaiting_ack, ready,
 * auth_failed, disconnected.  ``auth_failed`` also offers a button that
 * opens Home Assistant's re-authentication prompt.
 */

/* Cache-busting: propagate our own ?v= down the import graph (lit-base.js
 * forwards it to vendor/lit.js).  Static imports would drop the query and
 * pin the browser to a stale copy of lit after an upgrade. */
const _q = new URL(import.meta.url).search;
const { LitElement, html, css } = await import(`../lit-base.js${_q}`);
const { t, ensurePanelTranslations } = await import(`../localize.js${_q}`);
const { navigateTo, REAUTH_PATH } = await import(`../utils.js${_q}`);

/**
 * Phase → dot colour class.
 *
 * Labels and descriptions are **not** here: they are user-facing text and
 * live in the translation files under `config_panel.phase.*`, keyed by the
 * same phase name (see ../localize.js).
 */
const PHASE_DOTS = {
  starting: "dot-yellow",
  connecting: "dot-yellow",
  awaiting_ack: "dot-orange",
  ready: "dot-green",
  auth_failed: "dot-red",
  disconnected: "dot-red",
};

class SberStatusCard extends LitElement {
  static get properties() {
    return {
      /** Home Assistant object — carries `localize` for the panel strings. */
      hass: { type: Object },
      connected: { type: Boolean },
      phase: { type: String },
    };
  }

  constructor() {
    super();
    this.connected = false;
    this.phase = "disconnected";
  }

  static get styles() {
    return css`
      :host {
        display: block;
      }
      .connection-indicator {
        display: flex;
        align-items: center;
        gap: 8px;
        font-size: 16px;
        font-weight: 500;
      }
      .phase-desc {
        font-size: 12px;
        color: var(--secondary-text-color);
        margin-top: 4px;
        margin-left: 20px;
      }
      .reauth {
        margin: 8px 0 0 20px;
        background: var(--error-color, #f44336);
        color: #fff;
        border: none;
        border-radius: 4px;
        padding: 6px 14px;
        cursor: pointer;
        font: inherit;
      }
      .reauth:focus-visible {
        outline: 2px solid var(--primary-color, #03a9f4);
        outline-offset: 2px;
      }
      .dot {
        width: 12px;
        height: 12px;
        border-radius: 50%;
        display: inline-block;
        flex-shrink: 0;
      }
      .dot-green {
        background: var(--success-color, #4caf50);
      }
      .dot-red {
        background: var(--error-color, #f44336);
      }
      .dot-yellow {
        background: #ff9800;
        animation: pulse 1.5s ease-in-out infinite;
      }
      .dot-orange {
        background: #ff5722;
        animation: pulse 2s ease-in-out infinite;
      }
      @keyframes pulse {
        0%, 100% { opacity: 1; }
        50% { opacity: 0.4; }
      }
    `;
  }

  connectedCallback() {
    super.connectedCallback();
    ensurePanelTranslations(this.hass, this);
  }

  render() {
    const phase = PHASE_DOTS[this.phase] ? this.phase : "disconnected";
    return html`
      <div class="connection-indicator">
        <span class="dot ${PHASE_DOTS[phase]}"></span>
        ${t(this.hass, `phase.${phase}.label`)}
      </div>
      ${phase !== "ready" && phase !== "disconnected"
        ? html`<div class="phase-desc">${t(this.hass, `phase.${phase}.desc`)}</div>`
        : ""}
      ${phase === "auth_failed"
        ? html`<button class="reauth" @click=${() => navigateTo(REAUTH_PATH)}>
            ${t(this.hass, "panel.auth_failed_action")}
          </button>`
        : ""}
    `;
  }
}

customElements.define("sber-status-card", SberStatusCard);
