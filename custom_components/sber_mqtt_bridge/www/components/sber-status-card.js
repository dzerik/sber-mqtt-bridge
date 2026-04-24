/**
 * Sber MQTT Bridge — Connection status card component.
 *
 * Displays MQTT connection lifecycle phase with a coloured dot indicator
 * and descriptive text. Phases: starting, connecting, awaiting_ack, ready, disconnected.
 */

import { LitElement, html, css } from "../lit-base.js";

/** Phase metadata: color class, label, description. */
const PHASES = {
  starting: {
    dot: "dot-yellow",
    label: "Starting...",
    desc: "Waiting for Home Assistant to finish loading",
  },
  connecting: {
    dot: "dot-yellow",
    label: "Connecting...",
    desc: "Establishing MQTT connection to Sber cloud",
  },
  awaiting_ack: {
    dot: "dot-orange",
    label: "Awaiting Sber...",
    desc: "Connected, config published — waiting for Sber to acknowledge",
  },
  ready: {
    dot: "dot-green",
    label: "Ready",
    desc: "Fully operational — accepting commands from Sber",
  },
  disconnected: {
    dot: "dot-red",
    label: "Disconnected",
    desc: "Not connected to Sber MQTT broker",
  },
};

class SberStatusCard extends LitElement {
  static get properties() {
    return {
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

  render() {
    const p = PHASES[this.phase] || PHASES.disconnected;
    return html`
      <div class="connection-indicator">
        <span class="dot ${p.dot}"></span>
        ${p.label}
      </div>
      ${this.phase !== "ready" && this.phase !== "disconnected"
        ? html`<div class="phase-desc">${p.desc}</div>`
        : ""}
    `;
  }
}

customElements.define("sber-status-card", SberStatusCard);
