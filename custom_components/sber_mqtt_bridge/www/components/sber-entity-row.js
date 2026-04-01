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
      .badge-yellow {
        background: var(--warning-color, #ff9800);
      }
      .name-link {
        cursor: pointer;
        color: var(--primary-color, #03a9f4);
        text-decoration: none;
      }
      .name-link:hover {
        text-decoration: underline;
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

      /* ── Mobile: card layout ── */
      @media (max-width: 768px) {
        :host {
          display: flex;
          flex-wrap: wrap;
          align-items: center;
          position: relative;
          padding: 12px 12px 12px 15px;
          margin-bottom: 8px;
          border-radius: 8px;
          border: 1px solid var(--divider-color, #e0e0e0);
        }
        :host(.row-online) {
          border-left: 3px solid var(--success-color, #4caf50);
        }
        :host(.row-offline) {
          border-left: 3px solid var(--error-color, #f44336);
        }
        :host(.row-online) td,
        :host(.row-offline) td {
          background: none;
        }
        td {
          border-bottom: none;
          padding: 2px 0;
          font-size: 13px;
        }
        /* Checkbox — top-right corner */
        .cell-check {
          position: absolute;
          top: 10px;
          right: 10px;
          padding: 0;
        }
        /* Name — prominent, full width */
        .cell-name {
          flex: 0 0 100%;
          order: 1;
          font-size: 15px;
          font-weight: 500;
          padding-right: 36px;
          padding-bottom: 2px;
        }
        /* Entity ID — small, muted */
        .cell-eid {
          flex: 0 0 100%;
          order: 2;
          padding-bottom: 6px;
        }
        .cell-eid code {
          font-size: 11px;
          opacity: 0.6;
        }
        /* Metadata: category, room, state, online — inline row */
        .cell-cat,
        .cell-room,
        .cell-state,
        .cell-online {
          order: 3;
          margin-right: 12px;
          font-size: 12px;
        }
        .cell-cat::before,
        .cell-room::before,
        .cell-state::before {
          font-size: 10px;
          text-transform: uppercase;
          letter-spacing: 0.3px;
          color: var(--secondary-text-color);
          margin-right: 3px;
        }
        .cell-cat::before { content: "cat "; }
        .cell-room::before { content: "room "; }
        .cell-state::before { content: "state "; }
        /* Features — hidden on mobile (visible in detail dialog) */
        .cell-feat {
          display: none;
        }
        /* Actions — full width bottom row */
        .cell-actions {
          flex: 0 0 100%;
          order: 9;
          padding-top: 8px;
          border-top: 1px solid var(--divider-color, #e0e0e0);
          margin-top: 6px;
        }
        .actions-cell {
          flex-wrap: wrap;
          gap: 6px;
        }
        select {
          font-size: 13px;
          padding: 4px 6px;
        }
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

  _onLink() {
    this.dispatchEvent(
      new CustomEvent("link-entity", {
        detail: { entityId: this.device.entity_id },
        bubbles: true,
        composed: true,
      })
    );
  }

  _onShowDetail() {
    this.dispatchEvent(
      new CustomEvent("show-detail", {
        detail: { entity_id: this.device.entity_id },
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
    if (d?.is_online || !d?.is_filled) {
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
      <td class="cell-check">
        <input
          type="checkbox"
          .checked=${this.selected}
          @change=${this._onCheckChange}
        />
      </td>
      <td class="cell-eid"><code>${d.entity_id}</code></td>
      <td class="cell-name"><span class="name-link" @click=${this._onShowDetail}>${d.name || "\u2014"}</span>${d.linked_entities ? html` <span class="feature-tag" style="background:var(--info-color,#2196f3);color:#fff">\u{1F517} +${Object.keys(d.linked_entities).length}</span>` : ""}</td>
      <td class="cell-cat"><code>${d.sber_category}</code></td>
      <td class="cell-feat">
        <div class="features">
          ${(d.features || []).map(
            (f) => html`<span class="feature-tag">${f}</span>`
          )}
        </div>
      </td>
      <td class="cell-room">${d.room || "\u2014"}</td>
      <td class="cell-state">${d.state ?? "\u2014"}</td>
      <td class="cell-online">
        <span class="badge ${d.is_online ? "badge-green" : d.is_filled ? "badge-grey" : "badge-yellow"}">
          ${d.is_online ? "Online" : d.is_filled ? "Offline" : "Loading\u2026"}
        </span>
      </td>
      <td class="cell-actions">
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
          <button class="icon-btn" @click=${this._onLink} title="Link entities">
            \u{1F517}
          </button>
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
