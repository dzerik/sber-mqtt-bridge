/**
 * Sber MQTT Bridge — Connection status card component.
 *
 * Displays MQTT connection state with a coloured dot indicator.
 */

const LitElement = Object.getPrototypeOf(
  customElements.get("ha-panel-lovelace") ?? customElements.get("hui-view")
);
const html = LitElement?.prototype.html;
const css = LitElement?.prototype.css;

class SberStatusCard extends LitElement {
  static get properties() {
    return {
      connected: { type: Boolean },
    };
  }

  constructor() {
    super();
    this.connected = false;
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
      .dot {
        width: 12px;
        height: 12px;
        border-radius: 50%;
        display: inline-block;
      }
      .dot-green {
        background: var(--success-color, #4caf50);
      }
      .dot-red {
        background: var(--error-color, #f44336);
      }
    `;
  }

  render() {
    return html`
      <div class="connection-indicator">
        <span class="dot ${this.connected ? "dot-green" : "dot-red"}"></span>
        ${this.connected ? "Connected" : "Disconnected"}
      </div>
    `;
  }
}

customElements.define("sber-status-card", SberStatusCard);
