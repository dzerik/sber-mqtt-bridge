/**
 * Sber MQTT Bridge — Single entity row component.
 *
 * Renders one device row in the device table with inline actions
 * (delete, override category, sync one device).
 */

const LitElement = Object.getPrototypeOf(
  customElements.get("ha-panel-lovelace") ?? customElements.get("hui-view")
);
const html = LitElement?.prototype.html;
const css = LitElement?.prototype.css;

const OVERRIDABLE_CATEGORIES = [
  "auto",
  "light",
  "led_strip",
  "relay",
  "socket",
  "curtain",
  "window_blind",
  "gate",
  "hvac_ac",
  "hvac_radiator",
  "hvac_heater",
  "hvac_boiler",
  "hvac_underfloor_heating",
  "hvac_fan",
  "valve",
  "hvac_humidifier",
  "scenario_button",
  "hvac_air_purifier",
  "kettle",
  "tv",
  "vacuum_cleaner",
  "intercom",
];

class SberEntityRow extends LitElement {
  static get properties() {
    return {
      device: { type: Object },
      selected: { type: Boolean, reflect: true },
    };
  }

  constructor() {
    super();
    this.device = {};
    this.selected = false;
  }

  static get styles() {
    return css`
      :host {
        display: table-row;
      }
      :host([offline]) td {
        opacity: 0.55;
      }
      :host(.row-online) td {
        background: color-mix(in srgb, var(--success-color, #4caf50) 5%, transparent);
      }
      :host(.row-offline) td {
        background: color-mix(in srgb, var(--error-color, #f44336) 5%, transparent);
      }
      td {
        padding: 8px;
        border-bottom: 1px solid var(--divider-color, #e0e0e0);
        vertical-align: middle;
        font-size: 13px;
      }
      .features {
        display: flex;
        flex-wrap: wrap;
        gap: 4px;
      }
      .feature-tag {
        display: inline-block;
        padding: 1px 6px;
        border-radius: 4px;
        font-size: 11px;
        background: var(--secondary-background-color, #eee);
        color: var(--secondary-text-color);
      }
      .badge {
        display: inline-block;
        padding: 2px 8px;
        border-radius: 12px;
        font-size: 12px;
        font-weight: 500;
        color: #fff;
      }
      .badge-green {
        background: var(--success-color, #4caf50);
      }
      .badge-grey {
        background: #9e9e9e;
      }
      .actions-cell {
        display: flex;
        gap: 4px;
        align-items: center;
      }
      .icon-btn {
        background: none;
        border: none;
        cursor: pointer;
        padding: 4px;
        border-radius: 4px;
        font-size: 16px;
        line-height: 1;
        color: var(--secondary-text-color);
        transition: background 0.15s;
      }
      .icon-btn:hover {
        background: var(--secondary-background-color, #eee);
        color: var(--error-color, #f44336);
      }
      .icon-btn.sync:hover {
        color: var(--primary-color, #03a9f4);
      }
      select {
        font-size: 12px;
        padding: 2px 4px;
        border: 1px solid var(--divider-color, #ccc);
        border-radius: 4px;
        background: var(--card-background-color, #fff);
        color: var(--primary-text-color);
        cursor: pointer;
      }
      input[type="checkbox"] {
        cursor: pointer;
        width: 16px;
        height: 16px;
      }
    `;
  }

  _onCheckChange(e) {
    this.selected = e.target.checked;
    this.dispatchEvent(
      new CustomEvent("selection-changed", {
        detail: { entityId: this.device.entity_id, selected: this.selected },
        bubbles: true,
        composed: true,
      })
    );
  }

  _onDelete() {
    this.dispatchEvent(
      new CustomEvent("delete-entity", {
        detail: { entityId: this.device.entity_id },
        bubbles: true,
        composed: true,
      })
    );
  }

  _onOverrideChange(e) {
    this.dispatchEvent(
      new CustomEvent("override-changed", {
        detail: { entityId: this.device.entity_id, category: e.target.value },
        bubbles: true,
        composed: true,
      })
    );
  }

  _onSync() {
    this.dispatchEvent(
      new CustomEvent("sync-entity", {
        detail: { entityId: this.device.entity_id },
        bubbles: true,
        composed: true,
      })
    );
  }

  updated() {
    /* Apply row-level online/offline CSS class */
    const d = this.device;
    if (d?.is_online) {
      this.classList.add("row-online");
      this.classList.remove("row-offline");
    } else {
      this.classList.add("row-offline");
      this.classList.remove("row-online");
    }
  }

  render() {
    const d = this.device;
    if (!d || !d.entity_id) return html``;

    return html`
      <td>
        <input
          type="checkbox"
          .checked=${this.selected}
          @change=${this._onCheckChange}
        />
      </td>
      <td><code>${d.entity_id}</code></td>
      <td>${d.name || "\u2014"}${d.linked_entities ? html` <span class="feature-tag" style="background:var(--info-color,#2196f3);color:#fff">\u{1F517} +${Object.keys(d.linked_entities).length}</span>` : ""}</td>
      <td><code>${d.sber_category}</code></td>
      <td>
        <div class="features">
          ${(d.features || []).map(
            (f) => html`<span class="feature-tag">${f}</span>`
          )}
        </div>
      </td>
      <td>${d.room || "\u2014"}</td>
      <td>${d.state ?? "\u2014"}</td>
      <td>
        <span class="badge ${d.is_online ? "badge-green" : "badge-grey"}">
          ${d.is_online ? "Online" : "Offline"}
        </span>
      </td>
      <td>
        <div class="actions-cell">
          <select @change=${this._onOverrideChange}>
            ${OVERRIDABLE_CATEGORIES.map(
              (cat) => html`
                <option
                  value=${cat}
                  ?selected=${cat === d.sber_category || (cat === "auto" && !d._has_override)}
                >
                  ${cat}
                </option>
              `
            )}
          </select>
          <button class="icon-btn sync" @click=${this._onSync} title="Sync to Sber">
            \u{1F504}
          </button>
          <button class="icon-btn" @click=${this._onDelete} title="Remove entity">
            \u{1F5D1}
          </button>
        </div>
      </td>
    `;
  }
}

customElements.define("sber-entity-row", SberEntityRow);
