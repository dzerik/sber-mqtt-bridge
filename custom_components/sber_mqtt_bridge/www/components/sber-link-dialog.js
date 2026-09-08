/**
 * Sber MQTT Bridge — Entity Link Dialog.
 *
 * Modal dialog for managing entity links on an existing exposed device.
 * Shows related entities grouped by same-device / other devices with compatibility info.
 * Fires "links-saved" event when links are updated.
 */

/* Cache-busting: propagate our own ?v= down the import graph (lit-base.js
 * forwards it to vendor/lit.js).  Static imports would drop the query and
 * pin the browser to a stale copy of lit after an upgrade. */
const _q = new URL(import.meta.url).search;
const { LitElement, html, css } = await import(`../lit-base.js${_q}`);
const { t, ensurePanelTranslations } = await import(`../localize.js${_q}`);
const { deepActiveElement } = await import(`../utils.js${_q}`);
const { linkRoleLabel, roleNames } = await import(`../link-roles.js${_q}`);
const { dialogStyles, buttonStyles } = await import(`../shared-styles.js${_q}`);

class SberLinkDialog extends LitElement {
  static get properties() {
    return {
      hass: { type: Object },
      open: { type: Boolean, reflect: true },
      _entityId: { type: String },
      _category: { type: String },
      _candidates: { type: Array },
      _allowedRoles: { type: Array },
      _acceptedRoles: { type: Array },
      _selected: { type: Object },
      _loading: { type: Boolean },
      _saving: { type: Boolean },
      _error: { type: String },
    };
  }

  constructor() {
    super();
    this.open = false;
    this._reset();
  }

  _reset() {
    this._entityId = "";
    this._category = "";
    this._candidates = [];
    this._allowedRoles = [];
    this._acceptedRoles = [];
    this._selected = {};
    this._loading = false;
    this._saving = false;
    this._error = "";
  }

  connectedCallback() {
    super.connectedCallback();
    /* Modal keyboard contract: Escape closes. */
    this._escHandler = (e) => {
      if (this.open && e.key === "Escape") {
        e.stopPropagation();
        this.hide();
      }
    };
    document.addEventListener("keydown", this._escHandler);
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    if (this._escHandler) {
      document.removeEventListener("keydown", this._escHandler);
      this._escHandler = null;
    }
  }

  async show(entityId) {
    this._reset();
    this._entityId = entityId;
    this._returnFocusTo = deepActiveElement();
    this.open = true;
    await this.updateComplete;
    const dialog = this.shadowRoot.querySelector(".dialog");
    if (dialog) dialog.focus();
    await this._loadCandidates();
  }

  hide() {
    this.open = false;
    /* Return focus to the row action that opened the dialog (WCAG 2.4.3). */
    const target = this._returnFocusTo;
    this._returnFocusTo = null;
    if (target && typeof target.focus === "function") target.focus();
  }

  async _loadCandidates() {
    if (!this.hass || !this._entityId) return;
    this._loading = true;
    this._error = "";
    try {
      const result = await this.hass.callWS({
        type: "sber_mqtt_bridge/suggest_links",
        entity_id: this._entityId,
      });
      this._candidates = result.candidates || [];
      this._allowedRoles = result.allowed_roles || [];
      this._acceptedRoles = result.accepted_roles || [];
      this._category = result.category || "";
      /* Two passes, existing links first.  A saved link is the user's own
       * decision and always wins; only then does the backend's suggestion
       * fill a role still standing empty.
       *
       * The suggestion matters most here, not in the wizard: a device
       * added before this release never went through the wizard's energy
       * step, so this dialog is the only place its power / voltage /
       * current sensors can be found — and finding three sensors by hand
       * among every companion entity is exactly what nobody does. */
      const sel = {};
      const takenRoles = new Set();
      for (const c of this._candidates) {
        if (c.currently_linked && c.linked_role) {
          sel[c.entity_id] = true;
          takenRoles.add(c.linked_role);
        }
      }
      for (const c of this._candidates) {
        if (sel[c.entity_id] || !c.preselected) continue;
        /* One entity per role, same rule _toggle enforces by hand. */
        if (c.suggested_role && takenRoles.has(c.suggested_role)) continue;
        sel[c.entity_id] = true;
        if (c.suggested_role) takenRoles.add(c.suggested_role);
      }
      this._selected = sel;
    } catch (e) {
      this._candidates = [];
      this._acceptedRoles = [];
      this._error = e.message || t(this.hass, "link.load_failed");
    } finally {
      this._loading = false;
    }
  }

  /**
   * Toggle a link candidate, enforcing one entity per Sber role.
   *
   * ``_save`` maps candidates into ``{role: entity_id}``, so two
   * selections claiming the same role would silently collapse to the
   * last one.  Selecting a candidate therefore unselects the previous
   * holder of its role — the same guard sber-wizard applies.
   */
  _toggle(entityId) {
    const sel = { ...this._selected };
    if (sel[entityId]) {
      delete sel[entityId];
    } else {
      const picked = this._candidates.find((c) => c.entity_id === entityId);
      const role = picked?.suggested_role;
      if (role) {
        for (const other of this._candidates) {
          if (other.entity_id !== entityId && other.suggested_role === role) {
            delete sel[other.entity_id];
          }
        }
      }
      sel[entityId] = true;
    }
    this._selected = sel;
    this.requestUpdate();
  }

  async _save() {
    if (!this.hass) return;
    this._saving = true;
    try {
      const links = {};
      for (const c of this._candidates) {
        if (this._selected[c.entity_id] && c.compatible && c.suggested_role) {
          links[c.suggested_role] = c.entity_id;
        }
      }
      await this.hass.callWS({
        type: "sber_mqtt_bridge/set_entity_links",
        entity_id: this._entityId,
        links,
      });
      this.dispatchEvent(new CustomEvent("links-saved", {
        bubbles: true, composed: true,
        detail: { entity_id: this._entityId, links },
      }));
      this.hide();
    } catch (e) {
      this.dispatchEvent(new CustomEvent("links-error", {
        bubbles: true, composed: true,
        detail: { message: e.message || String(e) },
      }));
    } finally {
      this._saving = false;
    }
  }

  /**
   * One link candidate: checkbox, entity, role badge.
   *
   * The badge names the Sber slot the entity would fill.  It reads the
   * shared vocabulary, so `power` shows up next to `battery` looking
   * like a peer of it rather than like a raw field name — see
   * ``../link-roles.js``.
   *
   * @param {object} c - Candidate from ``suggest_links``.
   * @returns {*} A lit template for the row.
   */
  _renderCandidateRow(c) {
    const role = linkRoleLabel(this.hass, c.suggested_role, c.device_class);
    return html`
      <div class="candidate-row ${!c.compatible ? 'incompatible' : ''}">
        <input
          type="checkbox"
          aria-label="${t(this.hass, 'link.link_entity', { entity: c.friendly_name || c.entity_id })}"
          .checked=${!!this._selected[c.entity_id]}
          ?disabled=${!c.compatible}
          @change=${() => this._toggle(c.entity_id)}
        />
        <div class="candidate-info">
          <div class="candidate-name">${c.friendly_name}</div>
          <div class="candidate-id">${c.entity_id}</div>
        </div>
        <span class="role-badge ${c.compatible ? 'compatible' : ''}" title="${role.hint}">${role.text}</span>
        ${!c.compatible && c.device_class ? html`<span class="not-supported">not supported</span>` : ""}
      </div>
    `;
  }

  /**
   * Roles this device's Sber class takes but nothing can fill.
   *
   * `accepted_roles` is the full slot list — the readings the device
   * *could* report — while the candidates are what Home Assistant
   * actually offers.  The difference is the honest answer to "why is
   * there no current in the app?": there is no current sensor to link,
   * and no amount of scrolling this dialog will produce one.
   *
   * @returns {string[]} Role identifiers with no candidate, backend order.
   */
  _rolesWithoutCandidate() {
    const offered = new Set(
      this._candidates.map((c) => c.suggested_role).filter(Boolean),
    );
    return (this._acceptedRoles || []).filter((role) => !offered.has(role));
  }

  /**
   * The unfilled-slot footer, or `""` when every slot has a candidate.
   *
   * @returns {*} A lit template naming the roles nothing can fill.
   */
  _renderUnfilledRoles() {
    const missing = this._rolesWithoutCandidate();
    if (missing.length === 0) return "";
    return html`
      <div class="unfilled-roles">
        ${t(this.hass, "link.roles_unfilled", { roles: roleNames(this.hass, missing) })}
      </div>
    `;
  }

  _renderCandidates() {
    if (this._loading) return html`<div class="empty">${t(this.hass, "link.loading")}</div>`;
    if (this._error) return html`<div class="empty error-text">${this._error}</div>`;
    if (this._candidates.length === 0) {
      return html`
        <div class="empty">${t(this.hass, "link.none")}</div>
        ${this._renderUnfilledRoles()}
      `;
    }

    const sameDevice = this._candidates.filter(c => c.same_device);
    const otherDevices = this._candidates.filter(c => !c.same_device);

    return html`
      ${sameDevice.length > 0 ? html`
        <div class="section-label">${t(this.hass, "link.same_device")}</div>
        ${sameDevice.map(c => this._renderCandidateRow(c))}
      ` : ""}
      ${otherDevices.length > 0 ? html`
        <div class="section-label">${sameDevice.length > 0 ? "Other devices" : "Available entities"}</div>
        ${otherDevices.map(c => this._renderCandidateRow(c))}
      ` : ""}
      ${this._renderUnfilledRoles()}
    `;
  }

  static get styles() {
    return [dialogStyles, buttonStyles, css`
      .dialog { width: 92%; max-width: 560px; max-height: 80vh; }
      .info {
        font-size: 13px; color: var(--secondary-text-color); margin-bottom: 12px;
      }
      .section-label {
        font-size: 11px; font-weight: 600; text-transform: uppercase;
        color: var(--secondary-text-color); margin: 12px 0 4px; letter-spacing: 0.5px;
      }
      .section-label:first-child { margin-top: 0; }
      .candidate-row {
        display: flex; align-items: center; gap: 10px;
        padding: 8px 0; border-bottom: 1px solid var(--divider-color, #f0f0f0);
        font-size: 13px;
      }
      .candidate-row.incompatible { opacity: 0.4; }
      .candidate-row input[type="checkbox"] { width: 16px; height: 16px; cursor: pointer; }
      .candidate-info { flex: 1; min-width: 0; }
      .candidate-name { color: var(--primary-text-color); }
      .candidate-id { font-family: monospace; font-size: 11px; color: var(--secondary-text-color); }
      .role-badge {
        display: inline-block; padding: 2px 8px; border-radius: 4px;
        font-size: 11px; font-weight: 500;
        background: var(--secondary-background-color, #eee);
        color: var(--secondary-text-color);
      }
      .role-badge.compatible {
        background: color-mix(in srgb, var(--success-color, #4caf50) 15%, transparent);
        color: var(--success-color, #4caf50);
      }
      .not-supported {
        font-size: 11px; color: var(--error-color, #f44336);
      }
      .error-text { color: var(--error-color, #f44336); }
      .empty { text-align: center; padding: 24px; color: var(--secondary-text-color); font-style: italic; }
      /* Footer naming the roles nothing can fill — an explanation,
         not an action, so it stays quieter than a candidate row. */
      .unfilled-roles { padding: 8px 4px 0; font-size: 12px; color: var(--secondary-text-color); }
      /* Cancel + Save sit together on the right, unlike the wizard's
       * Back/Next split, so the shared footer's spacing is overridden. */
      .dialog-footer { justify-content: flex-end; }
    `];
  }

  render() {
    if (!this.open) return html``;
    const selectedCount = Object.keys(this._selected).length;

    return html`
      <div class="overlay" @click=${(e) => { if (e.target === e.currentTarget) this.hide(); }}>
        <div
          class="dialog"
          role="dialog"
          aria-modal="true"
          aria-labelledby="link-dialog-title"
          tabindex="-1"
        >
          <div class="dialog-header">
            <h2 id="link-dialog-title">${t(this.hass, "link.title")}</h2>
            <button class="close-btn" aria-label="${t(this.hass, 'link.close')}" @click=${this.hide}>\u2715</button>
          </div>

          <div class="body">
            <div class="info">
              <strong>${this._entityId}</strong> (${this._category})<br/>
              Select related entities to link as features of this device.
            </div>

            ${this._renderCandidates()}
          </div>

          <div class="dialog-footer">
            <button class="btn btn-secondary" @click=${this.hide}>${t(this.hass, "toolbar.cancel")}</button>
            <button class="btn btn-primary" ?disabled=${this._saving} @click=${this._save}>
              ${this._saving ? t(this.hass, "link.saving") : selectedCount > 0 ? t(this.hass, "link.save_count", { count: selectedCount }) : t(this.hass, "link.save")}
            </button>
          </div>
        </div>
      </div>
    `;
  }
}

customElements.define("sber-link-dialog", SberLinkDialog);
