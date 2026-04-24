"""Name/id normalization helpers for Sber device descriptors.

Python equivalents of the frontend helpers in ``www/utils.js``
(``slugify`` + ``isValidSalutName``).  Exposed so that:

* ``SberDevice`` pydantic validators can WARN on suspicious names
  (non-obvious symbols, empty, over length) — not fail.
* Places that build a fresh Sber device ``id`` from a human string
  (future YAML helpers, wizard fallbacks) can use one canonical
  slugifier instead of hand-rolling it.

**Note.** Sber C2C docs do NOT enforce strict symbols for ``name``.
Examples in developers.sber.ru include ``"Мой телевизор"``,
``"Смарт-телевизор"`` — cyrillic, latin, spaces, dashes all pass.
Salut voice-assistant rules (3-33 chars, cyrillic-only) apply to
``nicknames``, not to ``name``.  Therefore validators here are
deliberately **advisory** (WARN logs), not rejecting.
"""

from __future__ import annotations

import logging
import re

_LOGGER = logging.getLogger(__name__)

_CYRILLIC_TO_LATIN: dict[str, str] = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d",
    "е": "e", "ё": "yo", "ж": "zh", "з": "z", "и": "i",
    "й": "y", "к": "k", "л": "l", "м": "m", "н": "n",
    "о": "o", "п": "p", "р": "r", "с": "s", "т": "t",
    "у": "u", "ф": "f", "х": "kh", "ц": "ts", "ч": "ch",
    "ш": "sh", "щ": "sch", "ъ": "", "ы": "y", "ь": "",
    "э": "e", "ю": "yu", "я": "ya",
}
"""Lowercase Cyrillic → Latin mapping.  Mirrors ``www/utils.js`` so
that frontend-generated slugs and backend-generated slugs match."""

_SLUG_NON_ALNUM = re.compile(r"[^a-z0-9]")
_SLUG_MULTI_UNDERSCORE = re.compile(r"_+")

_SAFE_SBER_ID = re.compile(r"^[A-Za-z0-9_.\-]+$")
"""Symbols confirmed safe for ``device.id`` in Sber C2C.  Matches
what HA entity_id already produces (``domain.slug`` with
``[a-z0-9_]`` slug).  Emits WARN if something outside this set
slips in (e.g. YAML-configured id with Cyrillic)."""

_SALUT_NAME = re.compile(r"^[а-яёА-ЯЁ0-9 \-]{3,33}$")
"""Lenient Salut-friendly pattern: cyrillic letters, digits, space
and hyphen, 3-33 chars.  Used only as an advisory check (Sber's
own docs show names like ``Смарт-телевизор`` passing)."""


def slugify_sber_id(text: str) -> str:
    """Produce a Sber-safe slug from a human string.

    Lowercase, Cyrillic transliterated to Latin, everything else
    collapsed to underscore.  Leading / trailing underscores
    stripped.  Intended for building fallback ``device.id`` when the
    source is a free-form name (not an HA entity_id, which is
    already slugified).

    >>> slugify_sber_id("Удлинитель Кухня №1")
    'udlinitel_kukhnia_1'
    """
    if not text:
        return ""
    lower = text.lower()
    translit = "".join(_CYRILLIC_TO_LATIN.get(ch, ch) for ch in lower)
    no_symbols = _SLUG_NON_ALNUM.sub("_", translit)
    collapsed = _SLUG_MULTI_UNDERSCORE.sub("_", no_symbols)
    return collapsed.strip("_")


def is_safe_sber_id(value: str) -> bool:
    """Return True if ``value`` uses only symbols safe for Sber id.

    Empty strings are treated as **unsafe** (``False``).
    """
    return bool(value) and bool(_SAFE_SBER_ID.fullmatch(value))


def is_salut_friendly_name(value: str) -> bool:
    """Return True if ``value`` passes the Salut voice-assistant rule.

    Advisory only — Sber accepts names outside this pattern (e.g.
    pure-Latin names).  Useful for nicknames and for spotting names
    that Salut will refuse to recognize by voice.
    """
    return bool(value) and bool(_SALUT_NAME.fullmatch(value))


def warn_if_suspicious_name(entity_id: str, name: str) -> None:
    """Log a WARN if ``name`` looks risky for Sber registration.

    Non-fatal — we publish the name anyway.  Purpose is to surface
    likely causes of silent rejection in user logs without enforcing
    restrictions Sber itself does not document.

    Args:
        entity_id: HA entity id, included in the log line to identify
            the offender.
        name: Device name that will be sent to Sber.
    """
    if not name:
        _LOGGER.warning("Device %s has empty name — Sber may reject registration", entity_id)
        return
    if len(name) > 63:
        _LOGGER.warning(
            "Device %s name is %d chars (>63) — Sber may truncate or reject: %r",
            entity_id,
            len(name),
            name,
        )
    if not is_salut_friendly_name(name):
        _LOGGER.debug(
            "Device %s name %r is not Salut-friendly (cyrillic 3-33 + spaces/hyphens) — "
            "voice control by that exact name may not work; Sber app will still show it",
            entity_id,
            name,
        )


def warn_if_suspicious_id(entity_id: str) -> None:
    """Log a WARN if ``entity_id`` uses non-ASCII or exotic symbols.

    Non-fatal.  In practice HA entity_ids are always safe ASCII, so
    this is protection against YAML-configured ids only.
    """
    if not is_safe_sber_id(entity_id):
        _LOGGER.warning(
            "Device id %r contains symbols outside [A-Za-z0-9_.-] — "
            "Sber cloud may silently reject the device",
            entity_id,
        )
