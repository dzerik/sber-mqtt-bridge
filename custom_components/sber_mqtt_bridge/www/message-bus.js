/**
 * Sber MQTT Bridge — shared MQTT message feed.
 *
 * ``sber_mqtt_bridge/subscribe_messages`` is a *broadcast* feed: every
 * subscriber gets the full ring-buffer snapshot plus every subsequent
 * message.  DevTools and Replay both render that same feed, so opening the
 * DevTools tab used to create two independent WebSocket subscriptions —
 * double the traffic, two divergent buffers and two snapshot round-trips.
 *
 * This module owns exactly one subscription per bus instance and fans the
 * messages out to any number of listeners.  The subscription is lazy
 * (nothing is opened until the first listener attaches) and ref-counted
 * (torn down when the last listener detaches), so the feed costs nothing
 * while the user is on another tab.
 */

/** Hard cap on the live message buffer — the feed is unbounded otherwise. */
export const MAX_MESSAGES = 500;

/** WebSocket command backing the live feed. */
const SUBSCRIBE_COMMAND = "sber_mqtt_bridge/subscribe_messages";

/**
 * Fan-out buffer over a single ``subscribe_messages`` subscription.
 */
export class MessageBus {
  /**
   * @param {number} [max] - Buffer cap; older messages are dropped first.
   */
  constructor(max = MAX_MESSAGES) {
    this._max = max;
    this._messages = [];
    this._listeners = new Set();
    this._errorListeners = new Map();
    this._unsub = null;
    this._subscribing = false;
    this._hass = null;
  }

  /** @returns {Array} Current buffer (newest last). */
  get messages() {
    return this._messages;
  }

  /** @returns {boolean} True while a WS subscription is open. */
  get active() {
    return this._unsub !== null;
  }

  /** @returns {number} Number of attached listeners. */
  get listenerCount() {
    return this._listeners.size;
  }

  /**
   * Attach a listener and open the shared subscription if needed.
   *
   * The listener is called immediately with the current buffer so a newly
   * mounted component renders without waiting for the next snapshot.
   *
   * @param {object} hass - Home Assistant object (provides ``connection``).
   * @param {Function} listener - Called with the message array on change.
   * @param {Function} [onError] - Called with the error if subscribing fails.
   * @returns {Function} Idempotent detach function.
   */
  subscribe(hass, listener, onError) {
    if (hass) this._hass = hass;
    this._listeners.add(listener);
    if (onError) this._errorListeners.set(listener, onError);
    if (this._messages.length) listener(this._messages);
    this._ensureSubscribed();

    let released = false;
    return () => {
      if (released) return;
      released = true;
      this._listeners.delete(listener);
      this._errorListeners.delete(listener);
      if (this._listeners.size === 0) this._teardown();
    };
  }

  /**
   * Replace the buffer wholesale (e.g. after a manual ``message_log`` fetch).
   *
   * @param {Array} messages - New buffer contents.
   */
  replace(messages) {
    this._messages = (messages || []).slice(-this._max);
    this._emit();
  }

  /** Drop every buffered message and notify listeners. */
  clear() {
    this._messages = [];
    this._emit();
  }

  async _ensureSubscribed() {
    if (this._unsub || this._subscribing || !this._hass) return;
    this._subscribing = true;
    try {
      const unsub = await this._hass.connection.subscribeMessage(
        (event) => this._onEvent(event),
        { type: SUBSCRIBE_COMMAND }
      );
      if (this._listeners.size === 0) {
        /* Last listener detached while the round-trip was in flight —
         * drop the subscription instead of leaking it. */
        unsub();
        return;
      }
      this._unsub = unsub;
    } catch (err) {
      for (const onError of this._errorListeners.values()) onError(err);
    } finally {
      this._subscribing = false;
    }
  }

  _teardown() {
    if (this._unsub) {
      this._unsub();
      this._unsub = null;
    }
  }

  _onEvent(event) {
    if (!event) return;
    if (event.snapshot) {
      this._messages = event.snapshot.slice(-this._max);
    } else if (event.message) {
      const appended = [...this._messages, event.message];
      this._messages = appended.length > this._max ? appended.slice(-this._max) : appended;
    } else {
      return;
    }
    this._emit();
  }

  _emit() {
    for (const listener of [...this._listeners]) listener(this._messages);
  }
}

/**
 * Create an isolated bus (used by tests; the panel uses the singleton).
 *
 * @param {number} [max] - Buffer cap.
 * @returns {MessageBus} New bus.
 */
export function createMessageBus(max = MAX_MESSAGES) {
  return new MessageBus(max);
}

/**
 * Process-wide bus shared by the panel and its DevTools components.
 *
 * The panel hands this instance down as the ``bus`` property; components
 * fall back to it when rendered standalone, so there is never more than
 * one ``subscribe_messages`` subscription per browser tab.
 */
export const messageBus = createMessageBus();
