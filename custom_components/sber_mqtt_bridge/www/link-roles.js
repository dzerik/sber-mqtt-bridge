/**
 * Sber MQTT Bridge — human names and grouping for entity link roles.
 *
 * A *link role* is the slot a companion HA entity fills on an exposed
 * device: the battery sensor of a Zigbee curtain, the reed contact of an
 * impulse gate, the power meter of a smart socket.  The backend names
 * those slots with wire identifiers (`battery`, `signal_strength`,
 * `power`) — see `devices/base_entity.py::LinkableRole` — and three
 * different panel surfaces used to paint that identifier straight into
 * the interface: the wizard's sensor checklist, the link dialog's role
 * badge and the detail dialog's linked-entity card.
 *
 * That was tolerable while every role was a self-explanatory English
 * noun.  It stopped being tolerable with energy monitoring: `current`
 * reads as "the current one" to anyone who does not already know it
 * means amperage, and a Russian-speaking user got no help at all.
 *
 * ## What this module is for
 *
 * One place that answers "what do I call this role?", so the answer is
 * the same in all three surfaces and so a new role is localized by
 * adding a string, not by editing three components.
 *
 * The pair follows the same rule as `feature-labels.js`: the readable
 * name leads, the wire identifier stays one hover away — it is what the
 * user will find in the logs, in the WebSocket payloads and in Sber's
 * own documentation, so it must never become unreachable.
 *
 * ## Why the map is written as one arrow function per role
 *
 * `t(hass, "link_role.power")` has to appear as a literal call for
 * `tests/hacs/test_translations_consistency.py` to see the key: that
 * test greps the panel for `t(hass, "…")` and fails when the key is
 * missing from `strings.json`, either translation file or `EN_FALLBACK`.
 * A `` t(hass, `link_role.${role}`) `` would render identically and be
 * invisible to the guard — the four files could then drift apart
 * unnoticed, which is exactly the failure that test exists to catch.
 *
 * ## Usage
 *
 * ```js
 * const label = linkRoleLabel(this.hass, link.link_role);
 * html`<span title="${label.hint}">${label.text}</span>`;
 * ```
 */

/* Cache-busting: propagate our own ?v= down the import graph (lit-base.js
 * forwards it to vendor/lit.js).  Static imports would drop the query and
 * pin the browser to a stale copy of lit after an upgrade. */
const _q = new URL(import.meta.url).search;
const { t } = await import(`./localize.js${_q}`);

/**
 * Link roles carrying the electrical readings of a smart socket.
 *
 * Sber's `socket` and `relay` categories declare `power`, `voltage` and
 * `current` (https://developers.sber.ru/docs/ru/smarthome/c2c/power,
 * /voltage, /current — each names both).  Home Assistant integrations — Zigbee2MQTT, Tuya, Shelly,
 * ESPHome — publish those three as *separate* sensor entities next to
 * the switch, so on our side they arrive as linked entities, never as
 * attributes of the socket itself.  The wizard therefore has to show
 * them as a group the user can confirm at a glance.
 *
 * Order is the order they are rendered in, and it is deliberate: power
 * is the number people actually look at, current the one they rarely do.
 */
export const ENERGY_ROLES = Object.freeze(["power", "voltage", "current"]);

/**
 * Whether this device's Sber class takes electrical readings at all.
 *
 * Answers one question: is "no energy sensor found" worth saying?  On a
 * `light` it is noise; on a metering device it is the answer to "why
 * does the app not show my consumption?".
 *
 * The answer comes from the backend's own `accepted_roles` — every link
 * role the primary's Sber class declares, filled or not — rather than
 * from a category list kept here.  A hardcoded list was wrong the day
 * it was written: Sber's reference pages for `power`, `voltage` and
 * `current` name both `socket` *and* `relay` ("Устройства с этой
 * функцией"), so a Shelly 1PM exposed as a relay would never have been
 * explained.  Keeping the decision on the data means a category the
 * backend teaches to meter needs no edit here at all.
 *
 * @param {?object} device - Device descriptor from the backend
 *   (`list_devices_for_category`) or the `suggest_links` result.
 * @returns {boolean} True when at least one electrical role is accepted.
 *   False for a payload from a backend too old to send `accepted_roles`
 *   — the section then stays silent rather than claiming something the
 *   backend never said.
 */
export function acceptsEnergyRoles(device) {
  const accepted = device?.accepted_roles;
  return Array.isArray(accepted) && accepted.some((role) => ENERGY_ROLES.includes(role));
}

/**
 * Electrical roles the device accepts but has no candidate sensor for.
 *
 * A socket that reports power and voltage but no current is the common
 * case (Zigbee firmwares often omit one), and silence about the missing
 * third reading is what makes "why is there no current in the app?"
 * unanswerable.  The panel names it instead.
 *
 * @param {?object} device - Device descriptor carrying `accepted_roles`.
 * @param {Array<{link_role?: ?string}>} links - Energy link candidates
 *   the backend did find for it.
 * @returns {string[]} Role identifiers in {@link ENERGY_ROLES} order —
 *   empty when everything accepted has a candidate, and empty as well
 *   when the backend sent no `accepted_roles` (nothing is known to be
 *   missing, so nothing is claimed).
 */
export function missingEnergyRoles(device, links) {
  const accepted = device?.accepted_roles;
  if (!Array.isArray(accepted)) return [];
  const found = new Set((links || []).map((link) => link?.link_role));
  return ENERGY_ROLES.filter((role) => accepted.includes(role) && !found.has(role));
}

/**
 * Readable name per link role, keyed by the backend's wire identifier.
 *
 * One entry per `LinkableRole` declared in `devices/base_entity.py`.  A
 * role missing here is not a crash — {@link linkRoleLabel} falls back to
 * the identifier — but it does mean the panel shows `hcho` where it
 * could show "Formaldehyde", so keep the two lists together.
 *
 * @type {Readonly<Object<string, function(object): string>>}
 */
const ROLE_LABELS = Object.freeze({
  battery: (hass) => t(hass, "link_role.battery"),
  battery_low: (hass) => t(hass, "link_role.battery_low"),
  signal_strength: (hass) => t(hass, "link_role.signal_strength"),
  temperature: (hass) => t(hass, "link_role.temperature"),
  humidity: (hass) => t(hass, "link_role.humidity"),
  co2: (hass) => t(hass, "link_role.co2"),
  pm1: (hass) => t(hass, "link_role.pm1"),
  pm25: (hass) => t(hass, "link_role.pm25"),
  pm10: (hass) => t(hass, "link_role.pm10"),
  tvoc: (hass) => t(hass, "link_role.tvoc"),
  hcho: (hass) => t(hass, "link_role.hcho"),
  open_state: (hass) => t(hass, "link_role.open_state"),
  power: (hass) => t(hass, "link_role.power"),
  voltage: (hass) => t(hass, "link_role.voltage"),
  current: (hass) => t(hass, "link_role.current"),
});

/**
 * Whether a role is one of the socket's electrical readings.
 *
 * @param {?string} role - Backend link role identifier.
 * @returns {boolean} True for `power`, `voltage` and `current`.
 */
export function isEnergyRole(role) {
  return typeof role === "string" && ENERGY_ROLES.includes(role);
}

/**
 * Split a list of link candidates into energy readings and everything else.
 *
 * Preserves the incoming order inside each bucket, so the wizard keeps
 * whatever ordering the backend chose for the sensors it found.
 *
 * @param {Array<{link_role?: ?string}>} links - Link candidates as the
 *   backend describes them (`linked_native` / `linked_compatible`).
 * @returns {{energy: Array, other: Array}} The two buckets.  `energy` is
 *   empty whenever the backend reports no electrical roles — on every
 *   category that does not meter, and on a metering one whose device has
 *   no meter sensors.
 */
export function splitEnergyLinks(links) {
  const energy = [];
  const other = [];
  for (const link of links || []) {
    (isEnergyRole(link?.link_role) ? energy : other).push(link);
  }
  return { energy, other };
}

/**
 * Readable name and tooltip for a link role.
 *
 * @param {object} hass - Home Assistant object handed to the panel.
 * @param {?string} role - Backend link role identifier, e.g. `"power"`.
 * @param {?string} [fallback] - What to show when there is no role at all
 *   — the candidate's HA `device_class`, typically.
 * @returns {{text: string, hint: string}} `text` is what to render,
 *   `hint` what to put in `title=`.  `hint` is empty when it would only
 *   repeat `text`, so an unknown role does not get a tooltip echoing
 *   itself.
 */
export function linkRoleLabel(hass, role, fallback) {
  const identifier = role || fallback || "";
  if (!identifier) return { text: "?", hint: "" };
  const named = role ? ROLE_LABELS[role] : undefined;
  if (!named) return { text: identifier, hint: "" };
  const text = named(hass);
  return { text, hint: text === role ? "" : role };
}

/**
 * Comma-separated readable names of the roles present in a link list.
 *
 * Used by the wizard's confirmation step, where the point is to let the
 * user check *which* readings are about to be exposed without making
 * them count checkboxes on the previous step.
 *
 * @param {object} hass - Home Assistant object handed to the panel.
 * @param {Array<{link_role?: ?string}>} links - Selected link candidates.
 * @returns {string} e.g. `"Power, Voltage"`, or `""` for an empty list.
 */
export function linkRoleNames(hass, links) {
  return (links || [])
    .map((link) => linkRoleLabel(hass, link?.link_role, link?.device_class).text)
    .join(", ");
}

/**
 * Comma-separated readable names of bare role identifiers.
 *
 * Same output as {@link linkRoleNames}, for the places that hold roles
 * rather than candidates — the list of readings a device accepts but has
 * no sensor for, above all.
 *
 * @param {object} hass - Home Assistant object handed to the panel.
 * @param {Array<?string>} roles - Backend role identifiers.
 * @returns {string} e.g. `"Current"`, or `""` for an empty list.
 */
export function roleNames(hass, roles) {
  return (roles || []).map((role) => linkRoleLabel(hass, role).text).join(", ");
}
