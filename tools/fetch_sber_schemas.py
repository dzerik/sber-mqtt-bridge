#!/usr/bin/env python3
# ruff: noqa: T201  # CLI tool — print() is the intended interface
"""Fetch canonical Sber device schemas + function catalog.

Renders every device category page, every function page and the seven
normative structure pages on developers.sber.ru.  Builds two artifacts:

1. ``tests/hacs/__snapshots__/sber_schemas.json`` — per-category
   reference models (features, allowed_values, dependencies).
2. ``tests/hacs/__snapshots__/sber_full_spec.json`` — unified
   artifact containing every category + every function with type,
   range, usage and cross-references between them, plus the
   ``structures`` / ``protocol`` sections read off the pages that
   define the payload envelopes (value, state, model, device,
   allowed_values, error, common error).

What this tool can and cannot check
-----------------------------------

Only the *payloads* have an upstream reference.  Sber documents the
REST/webhook C2C profile; our MQTT transport is not documented at all —
``up/config``, ``up/status``, ``down/commands`` and the broker host do
not appear on a single page of the ``smarthome`` section.  What makes
these pages legitimate references anyway is ``/c2c/request-headers``,
which states that both profiles share the same structures.  So a drift
check can validate what we put *inside* a message, never the topic it
goes to.

How the pages are read
----------------------

Over plain HTTP.  The header of this file used to claim the pages were
client-side rendered and that Playwright was therefore required; that
was simply wrong, and it cost the project a browser download in CI for
every weekly run.  developers.sber.ru is Docusaurus with server-side
rendering: one ``GET`` returns the finished ``<article>`` — headings,
tables, ``<pre>`` examples and all — in about 240 KB and a fifth of a
second.  Nothing is fetched by JavaScript afterwards.

What the browser did give us for free was ``innerText``, and three of
its behaviours are load-bearing for the extractors below, so
:func:`inner_text` reproduces them from the markup (see its docstring):
block elements become line breaks, table cells are separated by tabs,
and the CMS's literal NUL bytes disappear.

Playwright stays as a fallback for the day Docusaurus moves to
client-side rendering: when a page comes back with no article (or a
suspiciously short one), :class:`DocFetcher` re-reads that page in a
browser rather than writing a quietly emptied snapshot.  The import is
optional — a missing playwright only matters if the fallback is
actually needed.

Usage:
    python tools/fetch_sber_schemas.py          # HTTP only, no browser

    pip install playwright && playwright install chromium
                                                # enables the fallback

CI runs this weekly.  Diff detection in the ``sber-compliance``
workflow creates a PR when the documentation changes upstream.
"""

from __future__ import annotations

import concurrent.futures
import contextlib
import json
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, NamedTuple, Protocol

try:  # pragma: no cover - exercised only when playwright is installed
    from playwright.sync_api import TimeoutError as PlaywrightTimeout
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover - the normal case in CI now

    class PlaywrightTimeout(Exception):  # type: ignore[no-redef]
        """Stand-in so the browser code paths still type-check without playwright.

        Raised by nothing: when playwright is missing the fallback is
        never entered, and :class:`DocFetcher` says so out loud instead
        of failing on an import nobody needs any more.
        """

    sync_playwright = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# All 29 Sber device categories (must match CATEGORY_REQUIRED_FEATURES
# in custom_components/sber_mqtt_bridge/sber_models.py).
CATEGORIES: tuple[str, ...] = (
    "light",
    "led_strip",
    "relay",
    "socket",
    "tv",
    "intercom",
    "hvac_ac",
    "hvac_radiator",
    "hvac_heater",
    "hvac_boiler",
    "hvac_underfloor_heating",
    "hvac_fan",
    "hvac_air_purifier",
    "hvac_humidifier",
    "kettle",
    "curtain",
    "window_blind",
    "gate",
    "valve",
    "sensor_temp",
    "sensor_pir",
    "sensor_door",
    "sensor_water_leak",
    "sensor_smoke",
    "sensor_gas",
    "sensor_air",  # 2026-07: датчик качества воздуха (co2/pm/tvoc/hcho)
    "scenario_button",
    "vacuum_cleaner",
    "hub",
)

BASE_URL = "https://developers.sber.ru/docs/ru/smarthome/c2c"
SCHEMAS_FILE = Path(__file__).parent.parent / "tests" / "hacs" / "__snapshots__" / "sber_schemas.json"
FULL_SPEC_FILE = Path(__file__).parent.parent / "tests" / "hacs" / "__snapshots__" / "sber_full_spec.json"

# Links on /functions to exclude (structural pages, not functions)
_STRUCTURAL_LINKS = (
    "types",
    "structure",
    "structures",
    "cloud-to-cloud",
    "api",
    "allowed_values",
    "dependencies",
    "device",
    "devices",
    "model",
    "state",
    "value",
    "overview",
    "intro",
    "functions",
    "discovery",
    "migration",
    "auth",
    "mqtt",
    "rest",
    "examples",
    "faq",
    "common-error",
    "logging",
    "testing",
    "webhook",
    "authorization",
    "bridge",
    "ca",
    "error",
)

# Function name regex in title: "Функция {name} | ..."
_FUNC_TITLE_RE = re.compile(r"Функция\s+([a-z_0-9]+)")

# Type declarations in function page text: "Тип данных: INTEGER(50,1000)" etc.
_TYPE_DECL_RE = re.compile(
    r"Тип данных:\s*([A-Z]+)(?:\s*\(([^)]+)\))?",
    flags=re.IGNORECASE,
)

# Trailing commas in Sber JSON examples (not valid JSON) — strip before parsing
_TRAILING_COMMA_RE = re.compile(r",(\s*[}\]])")

# One accepted value of an ENUM function, as the page words it:
#   "auto — скорость меняется автоматически."
# The value itself is a protocol slug; "+" and "-" are real ones (tv.source).
_ENUM_VALUE_RE = re.compile(r"^([a-z0-9_]+|\+|-)\s+—\s+\S", flags=re.MULTILINE)

# The heading that ends the vocabulary and starts the category list.  Its
# entries look exactly like enum values ("hvac_ac — кондиционеры."), so the
# scan MUST stop here or every category name becomes a fake enum value.
_ENUM_STOP_MARKER = "Устройства с этой функцией"

# Where the vocabulary starts.  Everything above it is prose about the type
# and the usage mode, which never carries the "value — description" shape.
_ENUM_START_MARKER = "Назначение:"

# "Способ использования: хранит состояние устройства и может менять его."
# Always the first line of a function page, above "Назначение:".
_USAGE_DECL_RE = re.compile(r"Способ использования:\s*([^\n]+)")

USAGE_STATE_READ_WRITE = "state_read_write"
"""Feature holds device state and Sber may change it (the common case)."""

USAGE_STATE_READ_ONLY = "state_read_only"
"""Feature holds device state but is reported only — no command accepted."""

USAGE_COMMAND_ONLY = "command_only"
"""Feature carries no state at all: it exists purely to accept a command.

Such a feature must be *declared* by the device yet never appears in a
state publish, which is exactly why the obligatory/conditional checks
have to run against declared features rather than the payload.
"""

USAGE_EVENT_ONLY = "event_only"
"""Feature notifies that something happened; it cannot be commanded.

Only ``pir`` is worded this way today — it is sent when motion is
detected and stays silent otherwise, so requiring it in every publish
reports every idle motion sensor as broken (issue #61).
"""

# Sber words the usage line in exactly four ways across all 96 functions.
# Keys are normalized (nbsp collapsed, trailing period dropped, lowercased)
# by :func:`classify_usage` before lookup.
_USAGE_MODES: dict[str, str] = {
    "хранит состояние устройства и может менять его": USAGE_STATE_READ_WRITE,
    "хранит состояние устройства, менять его не может": USAGE_STATE_READ_ONLY,
    "не хранит состояние устройства, может менять его": USAGE_COMMAND_ONLY,
    "уведомляет о состоянии устройства, менять его не может": USAGE_EVENT_ONLY,
}


# ---------------------------------------------------------------------------
# HTTP transport
# ---------------------------------------------------------------------------

USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
"""Sent on every request.  We are a guest on somebody else's site.

The string is the one the browser path used to send, kept identical so
the switch to plain HTTP cannot look like a different client to Sber.
"""

HTTP_TIMEOUT = 30
"""Seconds per request.  A docs page answers in ~0.2 s; main.js is ~6 MB."""

HTTP_ATTEMPTS = 3
"""Attempts per URL, including the first.  See :func:`fetch_html`."""

HTTP_RETRY_PAUSE = 2.0
"""Seconds before the second attempt; multiplied by the attempt number."""

HTTP_MAX_PARALLEL = 8
"""Upper bound on concurrent requests.  Deliberately modest."""

MIN_ARTICLE_CHARS = 500
"""Below this an ``<article>`` is treated as "did not really load".

The shortest real page in the crawl (``pir``) yields ~1100 characters,
so 500 leaves plenty of headroom while still catching the case this
guards against: Docusaurus moving to client-side rendering and serving
an empty shell that would otherwise be written to the snapshot as a
page with no features.
"""

_RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})
"""Status codes worth a second attempt.  A 404 is an answer, not a hiccup."""


class FetchResult(NamedTuple):
    """One HTTP GET, successful or not.

    Attributes:
        url: The URL that was requested.
        html: Decoded body, or ``None`` when the request failed.
        status: HTTP status when the server answered, else ``None``.
        error: Human-readable reason, or ``None`` on success.  A 404 and
            a connection timeout both land here but read differently on
            purpose — one means the page is gone, the other means the
            crawl is unreliable, and they call for different actions.
    """

    url: str
    html: str | None
    status: int | None
    error: str | None

    @property
    def ok(self) -> bool:
        """``True`` when a body came back."""
        return self.html is not None


def fetch_html(
    url: str,
    *,
    attempts: int = HTTP_ATTEMPTS,
    pause: float = HTTP_RETRY_PAUSE,
    timeout: int = HTTP_TIMEOUT,
    urlopen: Any = None,
    sleep: Any = None,
) -> FetchResult:
    """GET one page, retrying transient failures.

    Reconnaissance saw 5 of 269 page loads time out on a first pass, so
    a single failed request must not be reported as "Sber deleted this
    feature".  Network errors and the transient status codes in
    :data:`_RETRYABLE_STATUS` are retried with a growing pause; anything
    else (a 404 above all) is returned immediately — retrying it would
    only slow the run down and blur the diagnosis.

    Args:
        url: Absolute URL to read.
        attempts: Total attempts, including the first.
        pause: Base delay between attempts, multiplied by attempt number.
        timeout: Per-request timeout in seconds.
        urlopen: Injection point for tests; defaults to
            :func:`urllib.request.urlopen`.
        sleep: Injection point for tests; defaults to :func:`time.sleep`.

    Returns:
        A :class:`FetchResult`.  On failure it carries the last error
        seen, never a silent ``None``.
    """
    opener = urlopen or urllib.request.urlopen
    wait = sleep or time.sleep
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    result = FetchResult(url, None, None, "no attempt made")
    for attempt in range(1, max(attempts, 1) + 1):
        try:
            with opener(request, timeout=timeout) as response:
                status = getattr(response, "status", None)
                body = response.read()
            text = body.decode("utf-8", errors="replace") if isinstance(body, bytes) else str(body)
            return FetchResult(url, text, status, None)
        except urllib.error.HTTPError as exc:  # subclass of URLError — must come first
            result = FetchResult(url, None, exc.code, f"HTTP {exc.code} {exc.reason}")
            if exc.code not in _RETRYABLE_STATUS:
                return result
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            result = FetchResult(url, None, None, f"{type(exc).__name__}: {exc}")
        if attempt < max(attempts, 1):
            wait(pause * attempt)
    return result


def fetch_many(urls: list[str], **kwargs: Any) -> dict[str, FetchResult]:
    """Fetch several pages concurrently, at most :data:`HTTP_MAX_PARALLEL` at a time.

    Args:
        urls: URLs to read; duplicates are collapsed.
        **kwargs: Forwarded to :func:`fetch_html`.

    Returns:
        ``url → FetchResult`` for every requested URL.
    """
    unique = list(dict.fromkeys(urls))
    if not unique:
        return {}
    workers = min(HTTP_MAX_PARALLEL, len(unique))
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(fetch_html, url, **kwargs): url for url in unique}
        return {futures[future]: future.result() for future in concurrent.futures.as_completed(futures)}


# ---------------------------------------------------------------------------
# Minimal DOM + innerText
# ---------------------------------------------------------------------------

_VOID_TAGS = frozenset(
    ("area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr")
)
"""Elements that never have children, so they never open a scope."""

_UNRENDERED_TAGS = frozenset(("script", "style", "noscript", "template", "head"))
"""Elements whose text a browser never shows."""

_REPLACED_TAGS = frozenset(
    ("svg", "img", "canvas", "video", "audio", "object", "iframe", "input", "select", "textarea")
)
"""Elements that occupy space but contribute no text.

They matter anyway: the docs put an icon between two spaces
("температурой<span>&#65279; <svg/></span> освещения") and the browser
keeps both spaces because the icon separates them.  Dropping the icon
outright would silently join them into one and change the extracted
sentence, so :func:`inner_text` keeps a placeholder while it trims.
"""

_BLOCK_TAGS = frozenset(
    (
        "address", "article", "aside", "blockquote", "caption", "center", "dd", "details",
        "dialog", "dir", "div", "dl", "dt", "fieldset", "figcaption", "figure", "footer",
        "form", "h1", "h2", "h3", "h4", "h5", "h6", "header", "hgroup", "hr", "legend",
        "li", "main", "menu", "nav", "ol", "p", "pre", "section", "summary", "table",
        "tbody", "tfoot", "thead", "tr", "ul",
    )
)  # fmt: skip
"""Elements rendered as blocks, i.e. that force a line break around themselves."""

_HEADING_TAGS = ("h1", "h2", "h3", "h4")
"""Headings the two section-scanning extractors look at (mirrors the old JS)."""

_COLLAPSIBLE_WS_RE = re.compile(r"[ \t\n\r\f]+")
"""Whitespace CSS collapses into a single space outside ``<pre>``."""

_INVISIBLE_RE = re.compile("[\x00­​]")
"""Characters that occupy no space on screen and must not split a word.

* ``\\x00`` — 60 of the 125 pages carry a literal NUL mid-sentence
  ("хранит состоя\\x00ние"); the browser's parser dropped it, so the
  phrase matching downstream never saw one.
* ``\\u00ad`` (soft hyphen) and ``\\u200b`` (zero-width space) are
  hyphenation hints: the reader sees one word, so the extractors must
  see one word too.  No page carries them today — this is here so the
  day one does, ``classify_usage`` does not silently return ``None``.

The non-breaking space (``\\xa0``) is deliberately *not* in this set: it
is a real space, and :func:`normalize_spaces` is what folds it away at
the point of comparison.  Neither is the BOM (``\\ufeff``), which the
docs sprinkle around link icons — it is part of the text the browser
returned and is likewise handled by :func:`normalize_spaces`.
"""

_MARK_ICON = "\x01"
"""Placeholder for a rendered replaced element; removed at the very end."""

_MARK_PRE_SPACE = "\x02"
"""A space inside ``<pre>``: never collapsed, never trimmed."""

_MARK_BREAK = "\x05"
"""A line break produced by a block boundary, as opposed to a ``<br>``."""


class Element:
    """One HTML element in the tiny DOM :func:`parse_html` builds.

    Only what the extractors need is modelled: tag name, attributes,
    children (elements and text) and the parent link that makes
    :meth:`next_siblings` possible.
    """

    __slots__ = ("attrs", "children", "parent", "tag")

    def __init__(self, tag: str, attrs: dict[str, str | None], parent: Element | None = None) -> None:
        self.tag = tag
        self.attrs = attrs
        self.children: list[Element | str] = []
        self.parent = parent

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Element {self.tag}>"

    def iter_elements(self):
        """Yield every descendant element in document order."""
        for child in self.children:
            if isinstance(child, Element):
                yield child
                yield from child.iter_elements()

    def find_all(self, *tags: str) -> list[Element]:
        """Return descendants with any of ``tags``, in document order."""
        wanted = frozenset(tags)
        return [element for element in self.iter_elements() if element.tag in wanted]

    def find_first(self, *tags: str) -> Element | None:
        """Return the first descendant with any of ``tags``, or ``None``."""
        wanted = frozenset(tags)
        return next((element for element in self.iter_elements() if element.tag in wanted), None)

    def next_siblings(self) -> list[Element]:
        """Return the element siblings that follow this one."""
        if self.parent is None:
            return []
        siblings = [child for child in self.parent.children if isinstance(child, Element)]
        return siblings[siblings.index(self) + 1 :]

    @property
    def classes(self) -> str:
        """The ``class`` attribute, or ``""`` when absent."""
        return self.attrs.get("class") or ""

    @property
    def text(self) -> str:
        """This element's :func:`inner_text`."""
        return inner_text(self)


class _DomBuilder(HTMLParser):
    """Builds an :class:`Element` tree out of a served HTML page.

    Docusaurus output is React-generated and therefore well-formed, so
    the builder stays deliberately simple: it does not implement HTML5
    tree correction beyond closing unbalanced tags, because a page that
    needs it would be a page whose markup changed enough to warrant a
    human look anyway.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Element("#document", {})
        self._open: list[Element] = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        element = Element(tag, dict(attrs), self._open[-1])
        self._open[-1].children.append(element)
        if tag not in _VOID_TAGS:
            self._open.append(element)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._open[-1].children.append(Element(tag, dict(attrs), self._open[-1]))

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self._open) - 1, 0, -1):
            if self._open[index].tag == tag:
                del self._open[index:]
                return

    def handle_data(self, data: str) -> None:
        self._open[-1].children.append(data)


def parse_html(html: str) -> Element:
    """Parse a page into the tiny DOM above.

    Args:
        html: The served markup.

    Returns:
        The document root; its children are ``<html>`` and friends.
    """
    builder = _DomBuilder()
    builder.feed(html)
    builder.close()
    return builder.root


_HIDDEN_STYLE_RE = re.compile(r"display\s*:\s*none|visibility\s*:\s*hidden", re.IGNORECASE)
"""Inline styles that keep an element off the page."""


def _is_rendered(element: Element) -> bool:
    """Whether the element would be shown at all.

    Only the two signals visible in the markup are honoured — the
    ``hidden`` attribute and an inline ``display:none`` /
    ``visibility:hidden``.  Everything a stylesheet hides is invisible
    to us, which is why :func:`inner_text` is documented as an
    approximation rather than a reimplementation.
    """
    if "hidden" in element.attrs:
        return False
    return not _HIDDEN_STYLE_RE.search(element.attrs.get("style") or "")


def _collect_text_items(node: Element, items: list[tuple[str, Any]], preformatted: bool) -> None:
    """Walk ``node`` and append the raw ingredients of its rendered text.

    Item kinds: ``t`` collapsible text, ``r`` preformatted text, ``b``
    required line breaks, ``n`` an explicit ``<br>``, ``x`` a replaced
    element.  Kept separate because the join in :func:`inner_text`
    treats them differently.
    """
    for child in node.children:
        if isinstance(child, str):
            text = _INVISIBLE_RE.sub("", child)
            if preformatted:
                items.append(("r", text.replace(" ", _MARK_PRE_SPACE)))
            else:
                items.append(("t", _COLLAPSIBLE_WS_RE.sub(" ", text)))
            continue
        tag = child.tag
        if tag in _UNRENDERED_TAGS or not _is_rendered(child):
            continue
        if tag in _REPLACED_TAGS:
            items.append(("x", None))
            continue
        if tag == "br":
            items.append(("n", None))
            continue
        block = tag in _BLOCK_TAGS
        if block:
            # A paragraph is separated from its neighbours by a blank
            # line, every other block by a single break.
            items.append(("b", 2 if tag == "p" else 1))
        _collect_text_items(child, items, preformatted or tag == "pre")
        if block:
            items.append(("b", 2 if tag == "p" else 1))
        if tag in ("td", "th") and any(sibling.tag in ("td", "th") for sibling in child.next_siblings()):
            items.append(("t", "\t"))


def inner_text(node: Element) -> str:
    """Render an element the way the browser's ``innerText`` did.

    This is the one piece the browser used to provide, and three of its
    behaviours are load-bearing here:

    * **Line breaks.** ``Способ использования: …`` is matched with
      ``[^\\n]+``, and every ENUM value is matched at the start of a
      line.  Without block-level breaks the usage sentence swallows the
      rest of the page and the vocabulary disappears.
    * **Tabs between table cells.** ``_OBLIGATION_SENTENCE_RE`` excludes
      tabs precisely so a sentence cannot run from one cell into the
      next.
    * **Collapsed whitespace, but only where CSS collapses it.** Naively
      replacing tags with spaces breaks words apart — "хранит состоя ние
      устройства" — and every phrase match downstream then fails
      silently.  Text inside ``<pre>`` keeps its indentation, ``&shy;``,
      ``<wbr>`` and zero-width joins contribute nothing, and ``&nbsp;``
      survives collapsing (:func:`normalize_spaces` deals with it later).

    It is an approximation, not a reimplementation: without a CSS engine
    we cannot know that a ``<div>`` was styled ``display:inline-block``,
    and stylesheet-hidden nodes are included.  Both only ever add text
    that the extractors' anchors ignore.

    Args:
        node: The element to render.

    Returns:
        The element's text with line breaks, tabs and collapsed spaces.
    """
    items: list[tuple[str, Any]] = []
    _collect_text_items(node, items, node.tag == "pre")
    parts: list[str] = []
    pending = 0
    started = False
    line_open = False
    for kind, value in items:
        if kind == "b":
            if started:
                pending = max(pending, value)
                line_open = False
            continue
        if kind == "x":
            # An icon only matters between two pieces of text on one
            # line; on its own (a copy button, say) it renders no text
            # and must not open a line.
            if line_open:
                parts.append(_MARK_ICON)
            continue
        if kind == "t" and value.strip(" ") == "":
            # Whitespace between two blocks is not rendered at all.
            if not started or pending:
                continue
            parts.append(value if value == "\t" else " ")
            continue
        if pending:
            parts.append(_MARK_BREAK * pending)
            pending = 0
        if kind == "n":
            parts.append("\n")
            line_open = False
        else:
            parts.append(value)
            line_open = True
        started = True
    text = "".join(parts)
    text = re.sub(r" +", " ", text)
    text = re.sub(rf" +([\n{_MARK_BREAK}])", r"\1", text)
    text = re.sub(rf"([\n{_MARK_BREAK}]) +", r"\1", text)
    text = text.strip(_MARK_BREAK)
    return text.replace(_MARK_BREAK, "\n").replace(_MARK_ICON, "").replace(_MARK_PRE_SPACE, " ")


# ---------------------------------------------------------------------------
# Page objects: the eight things every extractor reads off a page
# ---------------------------------------------------------------------------


class DocPage(Protocol):
    """What an extractor needs from a documentation page.

    Two implementations satisfy it: :class:`HttpDocPage`, which reads
    the served markup, and :class:`BrowserDocPage`, which asks a live
    Playwright page the same questions.  Keeping the surface this narrow
    is what lets the browser stay a fallback instead of a requirement.
    """

    def title(self) -> str:
        """The ``<title>``, whitespace-collapsed, as ``document.title`` gives it."""

    def article_text(self) -> str:
        """Rendered text of the first ``article`` or ``main`` element."""

    def pre_texts(self) -> list[str]:
        """Rendered text of every ``<pre>``, in document order."""

    def meta(self) -> dict[str, str]:
        """``{"h1": …, "date": …}`` — page title and "Обновлено" stamp."""

    def features_table_rows(self) -> list[dict]:
        """Rows of the "Доступные функции устройства" table (may be empty)."""

    def category_intro(self) -> str:
        """Prose between that heading and its table (may be empty)."""

    def all_tables(self) -> list[list[list[str]]]:
        """Every table as ``[table][row][cell]`` text."""

    def c2c_hrefs(self) -> list[str]:
        """``href`` of every link pointing into ``/smarthome/c2c/``."""


_FEATURES_HEADING = "Доступные функции"
"""Heading that introduces the per-category feature table."""

_CHECK_MARK_RE = re.compile(r"[✔✓]")
"""Sber marks an obligatory feature with a check; ``✔︎*`` means conditional."""


class HttpDocPage:
    """A documentation page read over plain HTTP.

    Each method mirrors, one for one, the JavaScript the browser path
    used to evaluate — same selectors, same order, same fallbacks — so
    the two transports produce the same snapshot.
    """

    def __init__(self, url: str, html: str) -> None:
        """Parse the served markup.

        Args:
            url: The page's URL (kept for diagnostics).
            html: The served markup.
        """
        self.url = url
        self.root = parse_html(html)

    def _first(self, *tags: str) -> Element | None:
        return self.root.find_first(*tags)

    def title(self) -> str:
        """See :meth:`DocPage.title`."""
        element = self._first("title")
        return normalize_spaces(element.text) if element is not None else ""

    def _article(self) -> Element | None:
        """The first ``article`` or ``main``, matching ``querySelector('article, main')``."""
        return self._first("article", "main")

    def article_text(self) -> str:
        """See :meth:`DocPage.article_text`."""
        article = self._article()
        return article.text if article is not None else ""

    def pre_texts(self) -> list[str]:
        """See :meth:`DocPage.pre_texts`."""
        return [element.text for element in self.root.find_all("pre")]

    def meta(self) -> dict[str, str]:
        """See :meth:`DocPage.meta`."""
        heading = self._first("h1")
        stamp = next(
            (
                element
                for element in self.root.iter_elements()
                if element.attrs.get("id") == "date-update" or "date-update" in element.classes
            ),
            None,
        )
        return {
            "h1": heading.text if heading is not None else "",
            "date": stamp.text if stamp is not None else "",
        }

    def _section_heading(self, needle: str) -> Element | None:
        """First h1–h4 whose text contains ``needle``."""
        return next(
            (element for element in self.root.find_all(*_HEADING_TAGS) if needle in element.text),
            None,
        )

    def _features_table(self) -> Element | None:
        """The features table: a sibling of the heading, or nested in one.

        On some category pages (``sensor_air``) the table is wrapped in a
        ``<div>`` rather than being a direct sibling — the reason the
        browser extractor grew the same two-step lookup.
        """
        heading = self._section_heading(_FEATURES_HEADING)
        if heading is None:
            return None
        for sibling in heading.next_siblings():
            if sibling.tag in _HEADING_TAGS:
                return None
            if sibling.tag == "table":
                return sibling
            nested = sibling.find_first("table")
            if nested is not None:
                return nested
        return None

    def features_table_rows(self) -> list[dict]:
        """See :meth:`DocPage.features_table_rows`."""
        table = self._features_table()
        if table is None:
            return []
        rows: list[dict] = []
        for row in table.find_all("tr")[1:]:
            cells = [cell.text.strip() for cell in row.find_all("td")]
            marker = cells[1] if len(cells) > 1 else ""
            checked = bool(_CHECK_MARK_RE.search(marker))
            rows.append(
                {
                    "feature": cells[0] if cells else "",
                    "obligatory": checked and "*" not in marker,
                    "conditional": checked and "*" in marker,
                    "description": cells[2] if len(cells) > 2 else "",
                }
            )
        return rows

    def category_intro(self) -> str:
        """See :meth:`DocPage.category_intro`."""
        heading = self._section_heading(_FEATURES_HEADING)
        if heading is None:
            return ""
        parts: list[str] = []
        for sibling in heading.next_siblings():
            if sibling.tag in _HEADING_TAGS:
                break
            if sibling.tag == "table" or sibling.find_first("table") is not None:
                break
            parts.append(sibling.text)
        return "\n".join(parts)

    def all_tables(self) -> list[list[list[str]]]:
        """See :meth:`DocPage.all_tables`."""
        return [
            [[cell.text.strip() for cell in row.find_all("th", "td")] for row in table.find_all("tr")]
            for table in self.root.find_all("table")
        ]

    def c2c_hrefs(self) -> list[str]:
        """See :meth:`DocPage.c2c_hrefs`."""
        return [
            href
            for element in self.root.find_all("a")
            if "/smarthome/c2c/" in (href := element.attrs.get("href") or "")
        ]


class BrowserDocPage:
    """The same page, read through a live Playwright page.

    Used only as a fallback (see :class:`DocFetcher`); the JavaScript it
    evaluates is the code this tool ran against every page before the
    move to HTTP.
    """

    def __init__(self, page: Any) -> None:
        """Wrap a Playwright page that has already navigated to the URL."""
        self._page = page

    def title(self) -> str:
        """See :meth:`DocPage.title`."""
        return self._page.title()

    def article_text(self) -> str:
        """See :meth:`DocPage.article_text`."""
        return self._page.eval_on_selector("article, main", "el => el ? el.innerText : ''")

    def pre_texts(self) -> list[str]:
        """See :meth:`DocPage.pre_texts`."""
        return self._page.eval_on_selector_all("pre", "els => els.map(e => e.innerText)")

    def meta(self) -> dict[str, str]:
        """See :meth:`DocPage.meta`."""
        try:
            return self._page.evaluate(_PAGE_META_JS)
        except Exception:  # noqa: BLE001 — best-effort extraction
            return {"h1": "", "date": ""}

    def features_table_rows(self) -> list[dict]:
        """See :meth:`DocPage.features_table_rows`.

        Keeps the browser-only wait: the table is server-rendered, but a
        page that fell back to the browser did so because something was
        wrong with the plain markup, and re-checking a few times is
        cheaper than a false "category lost its table".
        """
        with contextlib.suppress(PlaywrightTimeout):
            self._page.wait_for_selector(f"h2:has-text('{_FEATURES_HEADING}')", timeout=8_000)
        rows = self._evaluate(_TABLE_EXTRACTOR_JS, [])
        for _ in range(3):
            if rows:
                break
            self._page.wait_for_timeout(600)
            rows = self._evaluate(_TABLE_EXTRACTOR_JS, [])
        return rows

    def category_intro(self) -> str:
        """See :meth:`DocPage.category_intro`."""
        return self._evaluate(_CATEGORY_INTRO_JS, "")

    def all_tables(self) -> list[list[list[str]]]:
        """See :meth:`DocPage.all_tables`."""
        return self._evaluate(_ALL_TABLES_JS, [])

    def c2c_hrefs(self) -> list[str]:
        """See :meth:`DocPage.c2c_hrefs`."""
        return self._page.eval_on_selector_all(
            'a[href*="/smarthome/c2c/"]',
            "els => els.map(a => a.getAttribute('href'))",
        )

    def _evaluate(self, script: str, default: Any) -> Any:
        try:
            return self._page.evaluate(script)
        except Exception:  # noqa: BLE001 — best-effort extraction
            return default


class DocFetcher:
    """Hands out :class:`DocPage` objects, HTTP first and browser second.

    The fallback exists because the failure it guards against is silent:
    if the docs site ever switches to client-side rendering, every
    ``<article>`` arrives empty, every extractor returns nothing, and the
    weekly job opens a drift PR that deletes half the specification. A
    slow run is a much better outcome than that, so an empty or
    suspiciously short article is re-read in a browser and loudly
    reported.
    """

    def __init__(self) -> None:
        """Start with an empty cache and no browser."""
        self._cache: dict[str, FetchResult] = {}
        self._playwright: Any = None
        self._browser: Any = None
        self._page: Any = None
        self.http_pages = 0
        """Pages served by the HTTP transport."""
        self.browser_pages = 0
        """Pages that needed the browser fallback."""
        self.http_errors: dict[str, str] = {}
        """``url → reason`` for every page HTTP could not deliver."""
        self.recovered: list[str] = []
        """URLs the browser fallback rescued."""

    def prefetch(self, urls: list[str]) -> None:
        """Warm the cache with a bounded-parallel sweep.

        Args:
            urls: Pages the caller is about to walk through in order.
        """
        self._cache.update(fetch_many([url for url in urls if url not in self._cache]))

    def load(self, url: str) -> DocPage | None:
        """Return the page, or ``None`` when neither transport could read it.

        Args:
            url: Absolute URL of a documentation page.

        Returns:
            A :class:`DocPage`, or ``None``.  Every failure is recorded
            in :attr:`http_errors` and printed by
            :func:`report_transport`.
        """
        result = self._cache.pop(url, None) or fetch_html(url)
        if result.ok:
            page = HttpDocPage(url, result.html or "")
            article = page.article_text()
            if len(article) >= MIN_ARTICLE_CHARS:
                self.http_pages += 1
                return page
            reason = f"article too short over HTTP ({len(article)} chars)"
        else:
            reason = result.error or "unknown HTTP failure"
        self.http_errors[url] = reason
        page = self._browser_page(url)
        if page is None:
            return None
        self.browser_pages += 1
        self.recovered.append(url)
        return page

    def _browser_page(self, url: str) -> DocPage | None:
        """Re-read ``url`` in a browser, launching one on first need."""
        if sync_playwright is None:
            print(f"    HTTP failed for {url} and playwright is not installed — page skipped")
            print("    (install it with: pip install playwright && playwright install chromium)")
            return None
        if self._page is None:
            print("    starting the browser fallback")
            self._playwright = sync_playwright().start()
            self._browser = self._playwright.chromium.launch(headless=True)
            self._page = self._browser.new_context(user_agent=USER_AGENT).new_page()
        print(f"    falling back to the browser for {url}")
        if not _load_page(self._page, url):
            return None
        return BrowserDocPage(self._page)

    def close(self) -> None:
        """Shut the browser down if one was ever started."""
        if self._browser is not None:
            self._browser.close()
            self._browser = None
        if self._playwright is not None:
            self._playwright.stop()
            self._playwright = None
        self._page = None


def report_transport(fetcher: DocFetcher) -> None:
    """Print how the pages were read and every HTTP failure seen.

    A 404 on a page we know exists and a connection timeout mean very
    different things — one is Sber removing a page, the other is a flaky
    crawl — so both are printed verbatim rather than folded into a count.

    Args:
        fetcher: The fetcher that served this run.
    """
    print(f"transport: {fetcher.http_pages} page(s) over HTTP, {fetcher.browser_pages} via the browser fallback")
    if not fetcher.http_errors:
        return
    print(f"WARNING: {len(fetcher.http_errors)} page(s) failed over HTTP:")
    for url, reason in sorted(fetcher.http_errors.items()):
        outcome = "recovered in the browser" if url in fetcher.recovered else "NOT recovered"
        print(f"  ! {url}\n      {reason} — {outcome}")


# ---------------------------------------------------------------------------
# Category schema extraction
# ---------------------------------------------------------------------------


def _load_page(page: Any, url: str) -> bool:
    """Navigate a Playwright page and wait for content.

    Browser-only, and only reached through :meth:`DocFetcher._browser_page`
    now that the crawl runs over HTTP.

    Args:
        page: A live Playwright page.
        url: Absolute URL to open.

    Returns:
        ``True`` when the page loaded, ``False`` on timeout.
    """
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=20_000)
        page.wait_for_selector("pre, article", timeout=10_000)
    except PlaywrightTimeout:
        return False
    return True


def _parse_json_block(text: str) -> dict | None:
    """Parse a <pre> block that should be a JSON object (lenient)."""
    text = text.strip()
    if not text.startswith("{"):
        return None
    cleaned = _TRAILING_COMMA_RE.sub(r"\1", text)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return None


def _normalize_category_schema(raw: dict) -> dict:
    """Strip instance-specific fields — keep only schema contract."""
    return {
        "category": raw.get("category"),
        "features": sorted(raw.get("features", [])),
        "allowed_values": raw.get("allowed_values") or {},
        "dependencies": raw.get("dependencies") or {},
    }


def extract_category_schema(page: DocPage, category: str) -> dict | None:
    """Read a category page: pick the <pre> whose JSON category matches.

    Also extracts the "Доступные функции устройства" table, which marks
    each feature as obligatory (``✔︎`` in column 2) or optional.  The
    obligatory set is the strictest feature contract per Sber's own docs.

    Args:
        page: The already-loaded category page.
        category: The category slug the page should describe.

    Returns:
        The schema, or ``None`` when the page carries no matching
        reference model.
    """
    pre_blocks = page.pre_texts()
    schema: dict | None = None
    for block in pre_blocks:
        data = _parse_json_block(block)
        if data and data.get("category") == category:
            schema = _normalize_category_schema(data)
            break
    if schema is None:
        return None

    # Extract obligatory + conditional features from the "Доступные функции" table.
    # obligatory  = ✔︎  (strict mandatory)
    # conditional = ✔︎* (at least one of the starred set must be present)
    #
    # На части страниц (напр. sensor_air) таблица обёрнута в <div> и не является
    # прямым sibling'ом заголовка — старый экстрактор её не находил и уходил в
    # silent-fallback (obligatory/conditional=[]), что давало ЛОЖНЫЙ дрифт при
    # живой таблице. Поиск вложенной таблицы есть в обоих транспортах;
    # hub-страницы без таблицы легитимно отработают пустым fallback ниже.
    table_rows = page.features_table_rows()
    if table_rows:
        schema["all_features"] = sorted({row["feature"] for row in table_rows if row["feature"]})
        schema["obligatory"] = sorted({row["feature"] for row in table_rows if row.get("obligatory")})
        schema["conditional"] = sorted({row["feature"] for row in table_rows if row.get("conditional")})
    else:
        # Fallback: no table found (rare — e.g. hub page).  Treat the
        # reference features as all-features and leave obligatory empty.
        schema["all_features"] = schema["features"]
        schema["obligatory"] = []
        schema["conditional"] = []

    # --- fields added on top of the original contract -------------------
    meta = page.meta()
    schema["doc_updated"] = extract_doc_updated(meta.get("date"))
    schema["feature_descriptions"] = {
        row["feature"]: normalize_spaces(_clean(row.get("description")))
        for row in table_rows
        if row.get("feature") and normalize_spaces(_clean(row.get("description")))
    }
    schema["device_example"] = extract_device_example(pre_blocks)
    intro = page.category_intro() or page.article_text()
    groups, unresolved = extract_any_of_groups(intro, set(schema["all_features"]))
    schema["conditional_any_of"] = groups
    schema["conditional_unresolved"] = unresolved
    return schema


_TABLE_EXTRACTOR_JS = """
() => {
  const HEAD = /^H[1-4]$/;
  const headings = Array.from(document.querySelectorAll('h1,h2,h3,h4'));
  const target = headings.find(h => h.innerText.includes('Доступные функции'));
  if (!target) return [];
  // The table is not always a direct sibling of the heading — on some
  // category pages (e.g. sensor_air) it is wrapped in a <div>. Scan the
  // following siblings until the next section heading and pick the first
  // <table>, whether it is the sibling itself or nested inside it.
  let table = null;
  let el = target.nextElementSibling;
  while (el && !HEAD.test(el.tagName)) {
    if (el.tagName === 'TABLE') { table = el; break; }
    const inner = el.querySelector ? el.querySelector('table') : null;
    if (inner) { table = inner; break; }
    el = el.nextElementSibling;
  }
  if (!table) return [];
  const rows = Array.from(table.querySelectorAll('tr'));
  return rows.slice(1).map(tr => {
    const cells = Array.from(tr.querySelectorAll('td')).map(td => td.innerText.trim());
    const marker = cells[1] || '';
    // Sber uses ✔︎ for strict mandatory and ✔︎* for "at least one of the
    // starred features must be present" (conditional mandatory).
    // Split the two so validators can enforce the strict set without
    // over-rejecting devices that expose only the conditional subset.
    const hasCheck = /[✔✓]/.test(marker);
    const isStrict = hasCheck && !marker.includes('*');
    const isConditional = hasCheck && marker.includes('*');
    return {
      feature: cells[0] || '',
      obligatory: isStrict,
      conditional: isConditional,
      // Third column is Sber's own Russian wording for the feature *in the
      // context of this category* — the only upstream label we have.
      description: cells[2] || '',
    };
  });
}
"""


# ---------------------------------------------------------------------------
# Category index drift check
# ---------------------------------------------------------------------------


def discover_advertised_categories(page: DocPage | None) -> set[str] | None:
    """Pull the set of category slugs advertised on the `/devices` index page.

    Args:
        page: The loaded ``/devices`` index, or ``None`` when it could
            not be read.

    Returns:
        The set, or ``None`` if the page failed to load (treated as
        soft-fail by the caller — drift check is skipped, main extraction
        continues). Used to detect when Sber adds or removes a category
        upstream so the hardcoded :data:`CATEGORIES` tuple can be updated.
    """
    if page is None:
        return None
    hrefs = page.c2c_hrefs()
    slugs: set[str] = set()
    prefix = "/docs/ru/smarthome/c2c/"
    for href in hrefs:
        if not href or not href.startswith(prefix):
            continue
        slug = href[len(prefix) :].strip("/")
        if not slug or slug == "devices" or slug in _STRUCTURAL_LINKS:
            continue
        # Categories are flat slugs; nested paths point to functions/sub-docs.
        if "/" in slug:
            continue
        slugs.add(slug)
    return slugs


_MAIN_JS_URL_RE = re.compile(r'https://media\.sberdevices\.ru/bsm-docs/[^"\s]+/main\.[a-f0-9]+\.js')
_MDX_SLUG_RE = re.compile(r'"@site/docs/ru/smarthome/c2c/([a-z0-9_-]+)\.mdx"')


def discover_slugs_via_main_js(timeout: int = HTTP_TIMEOUT) -> set[str] | None:
    """Extract every ``c2c/*.mdx`` slug embedded in the Docusaurus webpack bundle.

    The docs site is Docusaurus v3 — every route is registered inside
    ``main.<hash>.js`` as a chunk-map entry pointing at ``@site/docs/…mdx``.
    Reading that map is one HTTP round-trip (5–6 MB) and surfaces
    categories AND function pages AND structural pages in one go.

    MVP scope: kebab-case slugs (all structural pages like ``api-brief``,
    ``account-linking``) are filtered out. Distinguishing category vs
    function among the remaining snake_case + single-word slugs is left
    to the caller, which knows the current CATEGORIES set + the previous
    snapshot's function list.

    Args:
        timeout: Per-request timeout in seconds.

    Returns:
        The slug set, or ``None`` on any fetch failure (missing HTML,
        unresolvable main.js URL, network error) so callers can treat
        this as an optional signal.
    """

    def _get(url: str) -> str | None:
        # Same retrying fetcher as the crawl: main.js is ~6 MB and was
        # the one request that timed out on a live run, which showed up
        # as "main.js unreachable" and skipped the whole sweep.  The
        # bundle lives on media.sberdevices.ru, which refuses a
        # connection now and then even when the docs host is healthy, so
        # the reason is printed here rather than folded into the caller's
        # one-line warning — same rule as :func:`report_transport`.
        result = fetch_html(url, timeout=timeout)
        if not result.ok:
            print(f"  ! {url}\n      {result.error}")
        return result.html

    # Any real docs page will link the current main.js — /devices is fine
    # and matches Phase 0's own probe.
    html = _get(f"{BASE_URL}/devices")
    if not html:
        return None
    m = _MAIN_JS_URL_RE.search(html)
    if not m:
        return None
    main_js = _get(m.group(0))
    if not main_js:
        return None

    slugs = set(_MDX_SLUG_RE.findall(main_js))
    # Kebab-case slugs on this site are structural pages (api-*, account-*,
    # error-*, …) — drop them so only category/function candidates remain.
    return {s for s in slugs if "-" not in s}


def report_mainjs_drift(slugs: set[str] | None, known_functions: set[str]) -> None:
    """Print candidates for new categories/functions surfaced by main.js.

    Compares the main.js slug set against the hardcoded :data:`CATEGORIES`
    and the ``known_functions`` set (typically read from the previous
    snapshot). Slugs that aren't recognised as any of these — and aren't
    on a small list of well-known structural pages — get printed as
    ``? <slug>`` so the maintainer can decide if it's a new category,
    new function, or just another docs page.

    MVP: no auto-classification into category-vs-function. That would
    need scraping the /devices index anyway, which is exactly what the
    Playwright-based Phase 0 already does.
    """
    if slugs is None:
        print("WARNING: main.js unreachable — MVP slug discovery skipped")
        return
    # Structural pages (login guides, error refs, api reference, …) are
    # already enumerated in _STRUCTURAL_LINKS at module-scope. Reuse it so
    # updates land in one place instead of drifting between two lists.
    structural = frozenset(_STRUCTURAL_LINKS)
    unknown = slugs - set(CATEGORIES) - known_functions - structural
    print(f"main.js manifest carries {len(slugs)} non-kebab c2c slugs (one request, every route)")
    if not unknown:
        print("OK: every slug already accounted for by CATEGORIES + snapshot functions")
        return
    print(f"MAYBE-NEW: {len(unknown)} slug(s) not yet known to this tool:")
    for slug in sorted(unknown):
        # Distinguishing category vs function without extra fetches is
        # imperfect, but presence of an underscore + a common prefix is a
        # strong hint of category (sensor_air, hvac_*, etc.).
        hint = "category?" if slug.startswith(("sensor_", "hvac_", "light_", "scenario_")) else "function?"
        print(f"  ? {slug:35s} ({hint})")


def report_category_drift(advertised: set[str] | None) -> bool:
    """Compare advertised categories with hardcoded :data:`CATEGORIES`.

    Prints OK / WARNING. Returns ``True`` if no drift (or check skipped),
    ``False`` if additions or removals detected.
    """
    if advertised is None:
        print("WARNING: /devices index unreachable — category drift check skipped")
        return True
    known = set(CATEGORIES)
    new = advertised - known
    removed = known - advertised
    if not new and not removed:
        print(f"OK: all {len(known)} advertised categories match CATEGORIES")
        return True
    if new:
        suffix = "y" if len(new) == 1 else "ies"
        print(f"WARNING: {len(new)} new categor{suffix} on Sber docs:")
        for slug in sorted(new):
            print(f"  + {slug}")
        print("  Action: add to CATEGORIES in this file AND to CATEGORY_REQUIRED_FEATURES in sber_models.py")
    if removed:
        suffix = "y" if len(removed) == 1 else "ies"
        print(f"WARNING: {len(removed)} categor{suffix} no longer advertised:")
        for slug in sorted(removed):
            print(f"  - {slug}")
    return False


# ---------------------------------------------------------------------------
# Function catalog extraction
# ---------------------------------------------------------------------------


def list_function_slugs(page: DocPage | None) -> list[str]:
    """Get the list of function page slugs from the ``/functions`` index.

    Args:
        page: The loaded index page, or ``None`` when it could not be
            read — in which case there is nothing to discover and the
            caller falls back to the committed catalog.

    Returns:
        Sorted slugs, function pages only.
    """
    if page is None:
        return []
    hrefs = page.c2c_hrefs()
    slugs: set[str] = set()
    prefix = "/docs/ru/smarthome/c2c/"
    for href in hrefs:
        if not href or not href.startswith(prefix):
            continue
        slug = href[len(prefix) :].strip("/")
        if not slug or slug in _STRUCTURAL_LINKS:
            continue
        if slug in CATEGORIES:
            continue  # Category pages, not function pages
        slugs.add(slug)
    return sorted(slugs)


def slug_candidates(name: str) -> list[str]:
    """URL slugs a function *might* live at, most likely first.

    The canonical function name always uses underscores, while the docs
    site is inconsistent about the slug: ``open_set`` is served at
    ``/open_set`` but ``light_colour_temp`` at ``/light-colour-temp``.
    With no index entry to read the real href from, both spellings have
    to be tried.

    Args:
        name: Canonical function name (underscore form).

    Returns:
        One or two slugs; the kebab variant is omitted when the name has
        no underscore to convert.
    """
    kebab = name.replace("_", "-")
    return [name] if kebab == name else [name, kebab]


def plan_recovery_names(discovered_slugs: list[str], known_functions: set[str]) -> list[str]:
    """Functions the index stopped listing and that must be fetched directly.

    The ``/functions`` index is the only discovery source, so a page that
    silently drops out of it disappears from the snapshot — and with it
    from ``FEATURE_ENUM_VALUES`` / ``FEATURE_RANGES``.  Nothing downstream
    notices: the validator simply stops checking that feature.  Comparing
    the discovered slugs with the previously committed catalog turns that
    silent shrinkage into a direct re-fetch.

    Args:
        discovered_slugs: Slugs the index yielded this run.
        known_functions: Function names from the previous snapshot.

    Returns:
        Sorted names present in the previous snapshot but not covered by
        any discovered slug (slug dashes count as underscores).
    """
    covered = {slug.replace("-", "_") for slug in discovered_slugs}
    return sorted(known_functions - covered)


def extract_enum_values(article_text: str) -> list[str]:
    """Pull an ENUM function's accepted values out of its page text.

    The vocabulary is prose, not a table::

        Назначение: управляет скоростью вентилятора:

        auto — скорость меняется автоматически.
        quiet — тихий режим работы. ...

        Устройства с этой функцией
        hvac_ac — кондиционеры.

    Note the last two lines: the category list that follows has the very
    same shape, so the scan is bounded by
    :data:`_ENUM_STOP_MARKER` — without that bound every category name
    would be collected as an accepted value.

    This vocabulary is the *authoritative* one.  The ``allowed_values``
    block on a category page is only an illustrative example and is
    routinely shorter: the ``hvac_air_flow_power`` example omits
    ``quiet`` even though the function accepts it, so validating our own
    values against the category example would reject correct devices.

    Args:
        article_text: ``innerText`` of the function page's article.

    Returns:
        Accepted values in page order, de-duplicated.  Empty when the
        page has no vocabulary (every non-ENUM function, and the odd
        ENUM whose page words things differently — callers must treat
        "empty" as "unknown", never as "nothing is allowed").
    """
    section = _enum_section(article_text)
    seen: list[str] = []
    for match in _ENUM_VALUE_RE.finditer(section):
        value = match.group(1)
        if value not in seen:
            seen.append(value)
    return seen


def normalize_spaces(text: str) -> str:
    """Collapse Sber's typographic whitespace into plain single spaces.

    The docs are typeset with non-breaking spaces (``\\xa0``) and the odd
    zero-width BOM (``\\ufeff``) sprinkled mid-sentence: ``alarm_mute``
    reads "менять его не\\xa0может" while ``battery_low_power`` uses a
    plain space in the very same phrase.  Comparing the raw strings would
    split one wording into two, so every phrase is normalized first.

    Args:
        text: Raw ``innerText`` fragment as rendered by the docs site.

    Returns:
        The same text with all whitespace runs turned into single spaces
        and the leading/trailing whitespace stripped.
    """
    return re.sub(r"\s+", " ", text.replace("\xa0", " ").replace("\ufeff", "")).strip()


def classify_usage(usage: str) -> str | None:
    """Map a "Способ использования" sentence onto one of the four modes.

    Args:
        usage: The sentence as the page words it (raw or normalized).

    Returns:
        One of :data:`USAGE_STATE_READ_WRITE`, :data:`USAGE_STATE_READ_ONLY`,
        :data:`USAGE_COMMAND_ONLY`, :data:`USAGE_EVENT_ONLY` — or ``None``
        when Sber reworded the sentence.  ``None`` means *unknown*, never
        "no restriction": callers surface it as drift instead of guessing,
        because guessing here silently mislabels a command-only feature as
        state-bearing and the validator starts demanding a state that can
        never arrive.
    """
    return _USAGE_MODES.get(normalize_spaces(usage).rstrip(" .").lower())


def extract_usage(article_text: str) -> tuple[str | None, str | None]:
    """Pull the usage sentence + its classification off a function page.

    Args:
        article_text: ``innerText`` of the function page's article.

    Returns:
        ``(usage, usage_mode)``.  ``usage`` is the normalized sentence,
        ``usage_mode`` its :data:`_USAGE_MODES` classification.  Both are
        ``None`` when the page carries no usage line at all.
    """
    match = _USAGE_DECL_RE.search(article_text)
    if not match:
        return None, None
    usage = normalize_spaces(match.group(1))
    return usage, classify_usage(usage)


def extract_function_spec(page: DocPage, slug: str) -> dict | None:
    """Parse a single function page — name, type, range.

    ``used_in_categories`` is deliberately NOT extracted from the function
    page (see :func:`build_used_in_categories`).  The function's
    "Устройства с этой функцией" section is inconsistent — some pages omit
    it, others word the surrounding section differently — so we invert the
    graph from the per-category "Доступные функции" tables, which are the
    canonical source of truth.

    Args:
        page: The already-loaded function page.
        slug: The slug it was read from; used only to name the function
            when the title carries no "Функция <name>" heading.

    Returns:
        The function spec, or ``None`` when the page is not one.
    """
    title = page.title()
    name_match = _FUNC_TITLE_RE.search(title)
    # URL slugs sometimes use dashes; the canonical function name uses underscores.
    name = name_match.group(1) if name_match else slug.replace("-", "_")

    article_text = page.article_text()

    type_match = _TYPE_DECL_RE.search(article_text)
    type_name: str | None = None
    range_str: str | None = None
    if type_match:
        type_name = type_match.group(1).upper()
        range_str = (type_match.group(2) or "").strip() or None

    pre_blocks = page.pre_texts()

    usage, usage_mode = extract_usage(article_text)

    meta = page.meta()

    spec: dict = {
        "name": name,
        "type": type_name,
        "range": range_str,
        "usage": usage,
        "usage_mode": usage_mode,
        "examples": [b.strip() for b in pre_blocks if b.strip()],
        # --- fields added on top of the original contract ----------------
        "title_ru": extract_title_ru(meta.get("h1")),
        "doc_updated": extract_doc_updated(meta.get("date")),
        "model_declaration": classify_model_declaration(article_text),
        "narrowing": extract_narrowing(article_text),
        "state_example": extract_state_example(pre_blocks),
    }
    if type_name == "ENUM":
        values = extract_enum_values(article_text)
        if values:
            spec["enum_values"] = values
        descriptions = extract_enum_descriptions(article_text)
        if descriptions:
            spec["enum_descriptions"] = descriptions
    return spec


def report_usage_coverage(functions: dict[str, dict]) -> bool:
    """Print how many functions carry a recognised usage mode.

    Deliberately a warning and not a failure: a reworded usage sentence
    must still let the run finish and write the snapshot, so the drift
    check downstream can open a PR showing exactly which function lost
    its classification.  Failing here would abort before the PR exists.

    Args:
        functions: The function catalog, after extraction.

    Returns:
        ``True`` when every function is classified, ``False`` otherwise.
    """
    unknown = sorted(name for name, spec in functions.items() if not spec.get("usage_mode"))
    if not unknown:
        print(f"OK: all {len(functions)} functions carry a recognised usage mode")
        return True
    print(f"WARNING: {len(unknown)} function(s) with unrecognised 'Способ использования' wording:")
    for name in unknown:
        print(f"  ? {name:30s} usage={functions[name].get('usage')!r}")
    print("  Action: add the new wording to _USAGE_MODES in this file")
    return False


def build_used_in_categories(categories: dict[str, dict]) -> dict[str, list[str]]:
    """Invert ``categories[X].all_features`` into ``feature → [category, …]``.

    This is the authoritative source of the feature↔category link. Reading
    it off the function page (previously via ``_parse_categories_from_text``)
    was unreliable — several Sber pages either omitted the section or moved
    it under a different heading, causing common features like
    ``temperature`` / ``humidity`` / ``signal_strength`` to appear as
    orphaned in the snapshot.

    Args:
        categories: The per-category schemas as returned by
            :func:`extract_category_schema`.

    Returns:
        Mapping ``feature_name → sorted list of category slugs`` covering
        every feature seen in any category's ``all_features``.
    """
    used: dict[str, set[str]] = {}
    for cat_name, cat_schema in categories.items():
        for feature in cat_schema.get("all_features", ()):
            used.setdefault(feature, set()).add(cat_name)
    return {feat: sorted(cats) for feat, cats in used.items()}


# ---------------------------------------------------------------------------
# Page-level metadata: "Обновлено <дата>" stamp and the H1 heading
# ---------------------------------------------------------------------------

_PAGE_META_JS = """
() => ({
  h1: (document.querySelector('h1') || {}).innerText || '',
  date: (document.querySelector('#date-update, [class*="date-update"]') || {}).innerText || '',
})
"""

_CATEGORY_INTRO_JS = """
() => {
  const HEAD = /^H[1-4]$/;
  const headings = Array.from(document.querySelectorAll('h1,h2,h3,h4'));
  const target = headings.find(h => h.innerText.includes('Доступные функции'));
  if (!target) return '';
  // Only the paragraphs between the heading and the features table: the
  // obligation rules live there, and the table below repeats their wording
  // cell by cell, which is not prose and must not be parsed as such.
  const parts = [];
  let el = target.nextElementSibling;
  while (el && !HEAD.test(el.tagName)) {
    if (el.tagName === 'TABLE' || (el.querySelector && el.querySelector('table'))) break;
    parts.push(el.innerText || '');
    el = el.nextElementSibling;
  }
  return parts.join('\\n');
}
"""

_ALL_TABLES_JS = """
() => Array.from(document.querySelectorAll('table')).map(
  t => Array.from(t.querySelectorAll('tr')).map(
    tr => Array.from(tr.querySelectorAll('th,td')).map(c => c.innerText.trim())))
"""


def _clean(text: str | None) -> str:
    """Drop literal NUL bytes Sber's CMS leaves inside page copy.

    60 of the 125 reference pages carry a raw ``U+0000`` mid-sentence
    ("хранит состоя\\x00ние устройства", "✔\\x00\\x00︎").  Both transports
    already drop it — the browser's HTML parser silently, the HTTP one
    explicitly (see :data:`_INVISIBLE_RE`) — so this is the second line
    of defence, kept because the extractors are also called on text that
    went through neither: a previously committed snapshot, or a fragment
    pasted into a test.

    Args:
        text: Raw page text, or ``None``.

    Returns:
        The same text without NUL bytes; ``""`` for ``None``.
    """
    return (text or "").replace("\x00", "")


_DOC_UPDATED_RE = re.compile(r"Обновлено\s+(.+)")


def extract_doc_updated(date_text: str | None) -> str | None:
    """Pull the "Обновлено <дата>" stamp shown under every page title.

    Kept as the Russian string Sber prints ("4 апреля 2025"), never
    parsed into a ``date``: the point is to notice that the page changed,
    and re-formatting invites its own bugs (the day is sometimes
    zero-padded — "06 ноября 2025").

    This is the most sensitive drift signal available: it moves when Sber
    edits prose, adds a constraint or rewrites an example — all changes
    the structured extractors below cannot see.

    Args:
        date_text: ``innerText`` of the ``#date-update`` node.

    Returns:
        The date as printed, or ``None`` when the node is absent.
    """
    match = _DOC_UPDATED_RE.search(normalize_spaces(_clean(date_text)))
    return match.group(1).strip() if match else None


_H1_TITLE_RE = re.compile(r"^([a-z0-9_]+)\s*\((.+?)\)$")


def extract_title_ru(h1_text: str | None) -> str | None:
    """Pull the Russian label out of a function page's H1.

    Function pages title themselves ``light_colour (цвет)``; the
    parenthesised half is Sber's own wording for the feature and is what
    the panel should show instead of the protocol slug.

    Args:
        h1_text: ``innerText`` of the page's ``h1``.

    Returns:
        The Russian label, or ``None`` when the heading carries none
        (every category page — those are titled by the bare slug).
    """
    match = _H1_TITLE_RE.match(normalize_spaces(_clean(h1_text)))
    return match.group(2).strip() if match else None


MODEL_DECLARATION_REQUIRED = "must_declare"
"""The only model-declaration wording Sber uses: declare it in the model.

Every one of the 96 function pages carries the identical sentence
"Функция должна быть добавлена в описания моделей всех поддерживающих ее
устройств" — there is no "может" variant, so this value carries no
discriminating information on its own.  It is captured anyway for one
reason: the *absence* of the sentence on a page that used to have it is a
real upstream change, and today nothing would notice.
"""

_MODEL_DECLARATION_RE = re.compile(r"должна быть добавлена в описания моделей")


def classify_model_declaration(article_text: str) -> str | None:
    """Say whether the page states the feature must be declared in the model.

    Args:
        article_text: ``innerText`` of the function page's article.

    Returns:
        :data:`MODEL_DECLARATION_REQUIRED` when the canonical sentence is
        present, ``None`` when it is not.  ``None`` means *the wording
        changed*, not "declaring is optional" — no page has ever said
        that.
    """
    return MODEL_DECLARATION_REQUIRED if _MODEL_DECLARATION_RE.search(normalize_spaces(_clean(article_text))) else None


EXIT_OK = 0
"""Every page was read and every field the pages carry was extracted."""

EXIT_PAGES_FAILED = 1
"""At least one page could not be read at all — the snapshot is incomplete."""

EXIT_EXTRACTION_DEGRADED = 3
"""Every page was read, but a field or classification came out empty.

Distinct from :data:`EXIT_PAGES_FAILED` on purpose: the snapshot *was*
written and is still worth diffing, so CI keeps going and opens the
drift PR — but the diff may show the scraper losing data rather than
Sber changing the documentation, and a human has to be told which.
Silently returning 0 here is what let a degraded crawl look like a
clean one.
"""


NARROWING_ENUM_SUBSET = "enum_subset"
"""A model may publish a subset of the documented ENUM vocabulary."""

NARROWING_RANGE_AND_STEP = "range_and_step"
"""A model may shrink the documented numeric range *and* set any step."""

NARROWING_RANGE_ONLY = "range_only"
"""A model may shrink the documented numeric range; step is not mentioned."""

NARROWING_UNRECOGNISED = "unrecognised"
"""The narrowing sentence is present but worded in a way we cannot classify.

Surfaced rather than dropped: collapsing it to ``None`` would lose the
one fact the page does state — that this feature may be narrowed — and
leave a consumer unable to tell "permitted, wording new" apart from
"documentation silent".
"""

_NARROWING_SENTENCE_RE = re.compile(r"При описании модели устройства[^.]*\.")


def extract_narrowing(article_text: str) -> str | None:
    """Classify whether a model may narrow this feature's allowed values.

    Sber states the rule once per function, always opening with "При
    описании модели устройства", in two families of wording::

        …перечень доступных режимов работы функции можно сократить.
        …можно уменьшить диапазон принимаемых функцией значений либо
          изменить их шаг.

    The normative counterpart on the ``allowed_values`` page is blunt:
    "диапазон можно только сократить, а шаг можно установить любой".

    ``None`` means the page says nothing about narrowing this feature —
    and that is all it means.  No page anywhere states that a feature may
    *not* be narrowed, so a consumer must read ``None`` as "unconfirmed",
    never as a prohibition.

    Args:
        article_text: ``innerText`` of the function page's article.

    Returns:
        One of :data:`NARROWING_ENUM_SUBSET`,
        :data:`NARROWING_RANGE_AND_STEP`, :data:`NARROWING_RANGE_ONLY`,
        :data:`NARROWING_UNRECOGNISED`, or ``None`` when the page states
        no narrowing rule.
    """
    match = _NARROWING_SENTENCE_RE.search(_clean(article_text))
    if not match:
        return None
    sentence = normalize_spaces(match.group(0)).lower()
    if "сократить" in sentence:
        return NARROWING_ENUM_SUBSET
    if "диапазон" in sentence:
        return NARROWING_RANGE_AND_STEP if "шаг" in sentence else NARROWING_RANGE_ONLY
    return NARROWING_UNRECOGNISED


_LINE_COMMENT_RE = re.compile(r"//[^\n]*")


def _parse_json_block_lenient(text: str) -> dict | None:
    """Parse a documentation ``<pre>`` block that is *almost* JSON.

    Sber's examples carry ``// ...`` placeholder comments and trailing
    commas, both of which :func:`json.loads` rejects.  Kept separate from
    :func:`_parse_json_block` on purpose: that one feeds the category
    reference models already committed to the snapshot, and loosening it
    could silently change which ``<pre>`` block a category picks.

    Args:
        text: The block's ``innerText``.

    Returns:
        The parsed object, or ``None`` when the block is not a JSON
        object (schema blocks use unquoted pseudo-types such as
        ``"type": string`` and legitimately fail here).
    """
    stripped = _clean(text).strip()
    if not stripped.startswith("{"):
        return None
    cleaned = _LINE_COMMENT_RE.sub("", stripped)
    cleaned = _TRAILING_COMMA_RE.sub(r"\1", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return None


def extract_state_example(pre_blocks: list[str]) -> dict | None:
    """Pull the canonical ``{"key": …, "value": …}`` example off a function page.

    Every function page closes with "Пример описания состояния функции" —
    a real, parseable state packet showing the exact *shape* the value
    takes for that feature's type: ``integer_value`` as a **string**,
    ``bool_value`` as a bare boolean, ``colour_value`` as an ``{h, s, v}``
    object.  Nothing else in the documentation pins that down per
    feature, and getting it wrong (an INTEGER sent as a number) is
    accepted by every check we have today and then silently rejected by
    the cloud.

    Args:
        pre_blocks: ``innerText`` of every ``<pre>`` on the page.

    Returns:
        The first state entry from the example, unwrapped from its
        ``{"states": [...]}`` envelope, or ``None`` when no block parses.
    """
    for block in pre_blocks:
        data = _parse_json_block_lenient(block)
        if not isinstance(data, dict):
            continue
        for entry in data.get("states") or ():
            if isinstance(entry, dict) and "key" in entry and isinstance(entry.get("value"), dict):
                return entry
    return None


def _enum_section(article_text: str) -> str:
    """Slice the part of a function page that holds the ENUM vocabulary.

    Bounded by :data:`_ENUM_START_MARKER` and :data:`_ENUM_STOP_MARKER`:
    the category list that follows the vocabulary has the very same
    "slug — описание" shape, so an unbounded scan would collect every
    category name as an accepted value.

    Args:
        article_text: ``innerText`` of the function page's article.

    Returns:
        The bounded section, or ``""`` when the page has no vocabulary.
    """
    start = article_text.find(_ENUM_START_MARKER)
    if start == -1:
        return ""
    end = article_text.find(_ENUM_STOP_MARKER, start)
    return article_text[start : end if end != -1 else len(article_text)]


_ENUM_VALUE_DESC_RE = re.compile(r"^([a-z0-9_]+|\+|-)\s+—\s+(\S.*)$", flags=re.MULTILINE)


def extract_enum_descriptions(article_text: str) -> dict[str, str]:
    """Pull the Russian gloss Sber writes next to each ENUM value.

    The vocabulary is prose — "cooling — охлаждение воздуха." — and the
    right-hand half is currently thrown away by
    :func:`extract_enum_values`.  It is the only Russian wording for these
    protocol slugs that comes from Sber itself, so the panel can label a
    mode the same way the Salute app does instead of showing
    ``dehumidification``.

    Args:
        article_text: ``innerText`` of the function page's article.

    Returns:
        ``value → description`` for every documented value, in page
        order.  Empty for non-ENUM functions and for the two ENUMs whose
        pages carry no vocabulary at all.
    """
    section = _enum_section(_clean(article_text))
    descriptions: dict[str, str] = {}
    for match in _ENUM_VALUE_DESC_RE.finditer(section):
        value = match.group(1)
        if value not in descriptions:
            descriptions[value] = normalize_spaces(match.group(2)).rstrip(".")
    return descriptions


# The rule is one sentence, and it must stay one sentence: the same words
# are repeated inside the features table below it, where the row continues
# into the next cell.  A pattern allowed to run across a newline or a tab
# swallows part of the table and invents an "at least one of" group out of
# unrelated rows — which is exactly what happened to ``curtain`` before the
# tab was excluded (``innerText`` separates table cells with tabs, and how
# many of them fit on one rendered line depends on the viewport).
_OBLIGATION_SENTENCE_RE = re.compile(r"обязательно долж[^.\n\t]*\.")
_ANY_OF_MARKERS = ("хотя бы одна", "как минимум одна", "либо")
_FEATURE_TOKEN_RE = re.compile(r"[a-z][a-z0-9_]{2,}")


def extract_any_of_groups(article_text: str, known_features: set[str]) -> tuple[list[list[str]], list[str]]:
    """Read "at least one of these features" rules out of category prose.

    Four categories word it as a choice ("обязательно должен быть описан
    способ открытия: либо ``open_set``, либо ``open_percentage``, либо они
    оба") and two as a list ("хотя бы одна из следующих функций:
    ``temperature``, ``humidity``, …").  The table above that prose only
    marks such features with ``✔︎*``, and ``scenario_button`` is not even
    marked — its rule ("как минимум одна функция нажатия на кнопку") lives
    exclusively in this sentence, so today nothing checks it.

    Candidate tokens are intersected with ``known_features`` so a reworded
    sentence can never invent a feature name that does not exist.

    Args:
        article_text: ``innerText`` of the category page's article.
        known_features: Features the category's own table lists.

    Returns:
        ``(groups, unresolved)``.  ``groups`` holds the enumerable
        "at least one of" sets, each sorted so the snapshot does not
        churn when Sber reorders a sentence; ``unresolved`` holds
        sentences that
        announce such a rule but name fewer than two known features —
        those are real rules we could not machine-read and must be
        reported, never dropped.
    """
    groups: list[list[str]] = []
    unresolved: list[str] = []
    for match in _OBLIGATION_SENTENCE_RE.finditer(_clean(article_text)):
        sentence = normalize_spaces(match.group(0))
        if not any(marker in sentence for marker in _ANY_OF_MARKERS):
            continue
        tokens = [t for t in _FEATURE_TOKEN_RE.findall(sentence) if t in known_features]
        unique = sorted(set(tokens))
        if len(unique) >= 2:
            if unique not in groups:
                groups.append(unique)
        else:
            unresolved.append(sentence)
    return groups, unresolved


def extract_device_example(pre_blocks: list[str]) -> dict | None:
    """Pull the "Пример описания <устройства> пользователя" packet.

    The canonical device packet Sber publishes per category — the only
    upstream reference for the envelope ``sber_protocol.py`` builds.  Seven
    sensor categories show ``parent_id`` where the other 22 show
    ``groups``, which is Sber's own confirmation that hanging sensors off a
    hub is expected rather than a trick of ours.

    Args:
        pre_blocks: ``innerText`` of every ``<pre>`` on the category page.

    Returns:
        The device example, or ``None``.  Identified by ``default_name``,
        which the model example never carries.
    """
    for block in pre_blocks:
        data = _parse_json_block_lenient(block)
        if isinstance(data, dict) and "default_name" in data:
            return data
    return None


# ---------------------------------------------------------------------------
# Structure pages (value / state / model / device / allowed_values / errors)
# ---------------------------------------------------------------------------

STRUCTURE_PAGES: tuple[tuple[str, str], ...] = (
    ("value", "value"),
    ("state", "state"),
    ("model", "model"),
    ("device", "device"),
    ("allowed_values", "allowed_values"),
    ("error", "error"),
    ("common_error", "common-error"),
)
"""``snapshot key → docs slug`` for the seven normative structure pages.

These describe the payloads the bridge actually puts on the wire.  Note
that the MQTT *transport* itself is undocumented — no Sber page mentions
``up/config``, ``up/status`` or ``down/commands`` — but
``/c2c/request-headers`` states that the C2C and MQTT profiles share these
structures, so the pages are legitimate references for our payloads even
though they cannot validate our topics.
"""

_FIELD_TABLE_HEADERS: dict[str, str] = {
    "поле": "name",
    "тип": "type",
    "обязательное?": "obligatory",
    "описание": "description",
}
"""Header text → column role.  Matched by header, never by position.

Column order is stable today but the ``Обязательная?`` / ``Обязательное?``
heading already differs between the category and structure tables, so
positional indexing is exactly the kind of assumption that breaks
silently.
"""


def parse_field_table(rows: list[list[str]]) -> dict[str, dict]:
    """Turn a "Поле | Тип | Обязательное? | Описание" table into a mapping.

    Args:
        rows: The table as ``[row][cell]`` text, header row first.

    Returns:
        ``field name → {"type", "obligatory", "conditional",
        "description"}``.  Empty when the table has no recognisable
        header, so a restyled table degrades to "no data" (visible in the
        coverage report) rather than to wrong data.
    """
    if len(rows) < 2:
        return {}
    index: dict[str, int] = {}
    for position, title in enumerate(rows[0]):
        role = _FIELD_TABLE_HEADERS.get(normalize_spaces(title).lower())
        if role is not None:
            index[role] = position
    if "name" not in index:
        return {}

    def cell(row: list[str], role: str) -> str:
        position = index.get(role)
        return row[position] if position is not None and position < len(row) else ""

    fields: dict[str, dict] = {}
    for row in rows[1:]:
        name = normalize_spaces(cell(row, "name"))
        if not name:
            continue
        marker = cell(row, "obligatory")
        checked = "✔" in marker or "✓" in marker
        fields[name] = {
            "type": normalize_spaces(cell(row, "type")) or None,
            "obligatory": checked and "*" not in marker,
            "conditional": checked and "*" in marker,
            "description": _clean(cell(row, "description")).strip(),
        }
    return fields


def extract_structure_page(page: DocPage | None, slug: str) -> dict | None:
    """Read one structure page's field table.

    Args:
        page: The already-loaded structure page, or ``None`` when it
            could not be read.
        slug: Documentation slug, e.g. ``"allowed_values"``.

    Returns:
        ``{"slug", "title", "doc_updated", "fields"}`` or ``None`` when
        the page did not load.
    """
    if page is None:
        return None
    meta = page.meta()
    fields: dict[str, dict] = {}
    for rows in page.all_tables():
        fields = parse_field_table(rows)
        if fields:
            break
    return {
        "slug": slug,
        "title": normalize_spaces(_clean(meta.get("h1"))) or None,
        "doc_updated": extract_doc_updated(meta.get("date")),
        "fields": fields,
    }


_UPPER_TOKEN_LINE_RE = re.compile(r"^\s*([A-Z][A-Z_]{2,})\s*$", flags=re.MULTILINE)
# "h: 0–360" — the dash is an en-dash (U+2013) on the live page, but a
# plain hyphen has to be accepted too: it is one CMS edit away.
_COLOUR_RANGE_RE = re.compile(r"^\s*([hsv])\s*:\s*(\d+)\s*[–—-]\s*(\d+)\s*$", flags=re.MULTILINE)
_ERROR_CODE_RE = re.compile(r"^\s*(\d{3})\s*[–—-]\s*(.+?)\s*$", flags=re.MULTILINE)
_CHAR_LIMIT_RE = re.compile(r"количеств\w*\s+символов[^\d]{0,120}?(\d+)")


def derive_protocol_facts(structures: dict[str, dict]) -> dict:
    """Distil the structure pages into the handful of normative constants.

    Everything here is quoted, not remembered.  The same numbers are
    currently hardcoded across ``color_converter.py`` (HSV bounds),
    ``sber_models.py`` (``partner_meta`` ≤ 1024) and the validation-rules
    document, where they will keep working long after Sber changes them.

    Args:
        structures: Result of :func:`extract_structure_page` per key.

    Returns:
        Mapping with ``value_types``, ``value_field_types``,
        ``colour_ranges``, ``allowed_values_types``,
        ``partner_meta_max_chars`` and ``error_codes``.  A member is
        ``None``/empty when its source page did not yield it — callers
        must treat that as unknown, never as "no limit".
    """

    def description(structure: str, field: str) -> str:
        return ((structures.get(structure) or {}).get("fields") or {}).get(field, {}).get("description", "")

    value_fields = ((structures.get("value") or {}).get("fields") or {}).keys()
    return {
        "value_types": _UPPER_TOKEN_LINE_RE.findall(description("value", "type")),
        "value_field_types": {
            name: ((structures.get("value") or {}).get("fields") or {})[name].get("type")
            for name in value_fields
            if name.endswith("_value")
        },
        "colour_ranges": {
            component: [int(low), int(high)]
            for component, low, high in _COLOUR_RANGE_RE.findall(description("value", "colour_value"))
        },
        "allowed_values_types": _UPPER_TOKEN_LINE_RE.findall(description("allowed_values", "type")),
        "partner_meta_max_chars": (
            int(match.group(1)) if (match := _CHAR_LIMIT_RE.search(description("device", "partner_meta"))) else None
        ),
        "error_codes": {
            code: normalize_spaces(text)
            for key in ("error", "common_error")
            for code, text in _ERROR_CODE_RE.findall(description(key, "code"))
        },
    }


def merge_previous_structures(
    structures: dict[str, dict],
    previous: dict,
    failures: list[str],
) -> None:
    """Carry a failed structure page over from the committed snapshot.

    A structure page that fails to render would otherwise delete
    ``PARTNER_META_MAX_CHARS`` or the HSV bounds from the generated
    modules on the next codegen run — a portal hiccup silently turning
    into "no limit known".  Reusing the previous extraction keeps the
    constants and leaves the failure to the exit code and the report.

    Args:
        structures: Structures extracted this run (mutated in place).
        previous: The previously committed full spec, if any.
        failures: Keys that failed this run.
    """
    stale = (previous.get("structures") or {}) if isinstance(previous, dict) else {}
    for key in failures:
        carried = stale.get(key)
        if carried:
            structures[key] = carried
            print(f"  reusing committed extraction for {key} (page unreachable this run)")


# ---------------------------------------------------------------------------
# Coverage reporting for the added fields
# ---------------------------------------------------------------------------


def _coverage_line(label: str, present: int, total: int, *, expected_full: bool) -> bool:
    """Print one "N/M pages carry <field>" line.  Return True when healthy."""
    ok = present == total if expected_full else present > 0
    status = "OK   " if ok else "WARN "
    print(f"{status}{label:26s} {present:3d}/{total:3d}")
    return ok


FUNCTION_FIELD_COVERAGE: tuple[tuple[str, bool], ...] = (
    ("doc_updated", True),
    ("title_ru", True),
    ("model_declaration", True),
    ("state_example", True),
    ("narrowing", False),
    ("enum_descriptions", False),
)
"""``(field, must be present on every page)`` for the added function fields.

``narrowing`` and ``enum_descriptions`` are legitimately absent on most
pages — only 38 functions may be narrowed and only ENUMs have a
vocabulary — so those are reported without being demanded.
"""

CATEGORY_FIELD_COVERAGE: tuple[tuple[str, bool], ...] = (
    ("doc_updated", True),
    ("feature_descriptions", True),
    ("device_example", True),
    ("conditional_any_of", False),
)
"""``(field, must be present on every category)`` for the added fields."""


def report_added_field_coverage(
    functions: dict[str, dict],
    categories: dict[str, dict],
) -> bool:
    """Print how many pages yielded each added field.

    A scraper degrades by quietly extracting less than it used to, so
    every added field is counted against the number of pages that could
    have carried it.  Fields marked as mandatory print ``WARN`` the moment
    a single page stops yielding them.

    Args:
        functions: The function catalog after extraction.
        categories: The category schemas after extraction.

    Returns:
        ``True`` when every mandatory field reached full coverage.
    """
    healthy = True
    print("function pages:")
    for field, expected_full in FUNCTION_FIELD_COVERAGE:
        present = sum(1 for spec in functions.values() if spec.get(field))
        healthy &= _coverage_line(field, present, len(functions), expected_full=expected_full)
    print("category pages:")
    for field, expected_full in CATEGORY_FIELD_COVERAGE:
        present = sum(1 for schema in categories.values() if schema.get(field))
        healthy &= _coverage_line(field, present, len(categories), expected_full=expected_full)
    missing_narrowing = sorted(
        name for name, spec in functions.items() if spec.get("narrowing") == NARROWING_UNRECOGNISED
    )
    if missing_narrowing:
        healthy = False
        print(f"WARNING: {len(missing_narrowing)} function(s) state a narrowing rule we cannot classify:")
        for name in missing_narrowing:
            print(f"  ? {name}")
        print("  Action: extend extract_narrowing() in this file")
    unresolved = {
        name: schema["conditional_unresolved"]
        for name, schema in categories.items()
        if schema.get("conditional_unresolved")
    }
    if unresolved:
        print(f"NOTE: {len(unresolved)} category page(s) state an 'at least one of' rule we cannot enumerate:")
        for name, sentences in sorted(unresolved.items()):
            for sentence in sentences:
                print(f"  ? {name}: {sentence}")
        print("  These rules exist only as prose and need a hand-written check.")
    return healthy


def report_structure_coverage(structures: dict[str, dict], protocol: dict) -> bool:
    """Print what the structure pages yielded, field counts and constants.

    Returns:
        ``True`` when every page produced a field table and every derived
        constant came out non-empty.
    """
    healthy = True
    for key, slug in STRUCTURE_PAGES:
        fields = (structures.get(key) or {}).get("fields") or {}
        # There is no "of N" here — how many fields a structure page ought to
        # have is exactly what the page decides.  Zero is the only failure.
        status = "OK   " if fields else "WARN "
        print(f"{status}{key} ({slug}): {len(fields)} field(s)")
        healthy &= bool(fields)
    for name in ("value_types", "colour_ranges", "allowed_values_types", "error_codes"):
        if not protocol.get(name):
            healthy = False
            print(f"WARNING: derived constant {name!r} came out empty")
    if protocol.get("partner_meta_max_chars") is None:
        healthy = False
        print("WARNING: partner_meta character limit not found on the device page")
    else:
        print(f"OK   partner_meta_max_chars    {protocol['partner_meta_max_chars']}")
    return healthy


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


def _write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    """Fetch all categories + functions, write two snapshots.

    Returns:
        :data:`EXIT_OK`, :data:`EXIT_PAGES_FAILED` when a page could not be
        read at all, or :data:`EXIT_EXTRACTION_DEGRADED` when every page was
        read but the coverage reports found the extraction incomplete.  The
        last one still writes the snapshots — see the constant.
    """
    categories: dict[str, dict] = {}
    category_failures: list[str] = []

    functions: dict[str, dict] = {}
    function_failures: list[str] = []

    structures: dict[str, dict] = {}
    structure_failures: list[str] = []

    # The committed spec is both the "known functions" seed for the index
    # drift check and the fallback for a structure page that fails to
    # render (see merge_previous_structures).
    previous_spec: dict = {}
    if FULL_SPEC_FILE.exists():
        try:
            previous_spec = json.loads(FULL_SPEC_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            previous_spec = {}

    fetcher = DocFetcher()
    try:
        # Phase 0: detect drift between hardcoded CATEGORIES and upstream
        # /devices index. Soft-warning only — extraction continues either way.
        print("=== Phase 0: category index drift check ===")
        advertised = discover_advertised_categories(fetcher.load(f"{BASE_URL}/devices"))
        report_category_drift(advertised)
        print()

        # Phase 0b: MVP discovery via the main.js webpack manifest.
        # See discover_slugs_via_main_js() for rationale — this surfaces
        # BOTH new categories and new function pages in a single HTTP hop.
        print("=== Phase 0b: main.js manifest sweep ===")
        # Seed "known functions" from the previously-committed snapshot so
        # we don't re-flag every existing function on a fresh checkout.
        known_functions: set[str] = set((previous_spec.get("functions") or {}).keys())
        report_mainjs_drift(discover_slugs_via_main_js(), known_functions)
        print()

        # Phase 1: category schemas
        print(f"=== Phase 1: {len(CATEGORIES)} category schemas ===")
        fetcher.prefetch([f"{BASE_URL}/{category}" for category in CATEGORIES])
        for idx, category in enumerate(CATEGORIES, start=1):
            print(f"[{idx:2d}/{len(CATEGORIES)}] Fetching category {category}...", end=" ", flush=True)
            page = fetcher.load(f"{BASE_URL}/{category}")
            schema = extract_category_schema(page, category) if page is not None else None
            if schema is None:
                print("MISSING")
                category_failures.append(category)
            else:
                print(f"OK ({len(schema['features'])} features)")
                categories[category] = schema

        # Phase 1b: normative structure pages.  These are not categories
        # and not functions — they define the envelopes (value, state,
        # model, device, allowed_values, error) our MQTT payloads are made
        # of, and until now none of them was read at all.
        print(f"\n=== Phase 1b: {len(STRUCTURE_PAGES)} structure pages ===")
        fetcher.prefetch([f"{BASE_URL}/{slug}" for _, slug in STRUCTURE_PAGES])
        for key, slug in STRUCTURE_PAGES:
            print(f"Fetching structure {slug}...", end=" ", flush=True)
            structure = extract_structure_page(fetcher.load(f"{BASE_URL}/{slug}"), slug)
            if structure is None or not structure.get("fields"):
                print("MISSING")
                structure_failures.append(key)
            else:
                print(f"OK ({len(structure['fields'])} fields)")
                structures[key] = structure
        if structure_failures:
            merge_previous_structures(structures, previous_spec, structure_failures)

        # Phase 2: function catalog
        print("\n=== Phase 2: function catalog ===")
        function_slugs = list_function_slugs(fetcher.load(f"{BASE_URL}/functions"))
        print(f"Discovered {len(function_slugs)} function pages")
        fetcher.prefetch([f"{BASE_URL}/{slug}" for slug in function_slugs])
        for idx, slug in enumerate(function_slugs, start=1):
            print(f"[{idx:3d}/{len(function_slugs)}] Fetching function {slug}...", end=" ", flush=True)
            page = fetcher.load(f"{BASE_URL}/{slug}")
            spec = extract_function_spec(page, slug) if page is not None else None
            if spec is None or spec.get("type") is None:
                print("MISSING")
                function_failures.append(slug)
                continue
            name = spec["name"]
            # Drop oversized example list from functions snapshot
            spec = {k: v for k, v in spec.items() if k != "examples"}
            functions[name] = spec
            print(f"OK ({spec['type']})")

        # Phase 2b: the index is the only discovery source, so anything it
        # drops would silently vanish from the catalog.  Re-fetch such pages
        # by their slug directly (see plan_recovery_names).
        recovery = [n for n in plan_recovery_names(function_slugs, known_functions) if n not in functions]
        if recovery:
            print(f"\n=== Phase 2b: {len(recovery)} known function(s) missing from the index ===")
            for name in recovery:
                print(f"Re-fetching {name} by slug...", end=" ", flush=True)
                for candidate in slug_candidates(name):
                    page = fetcher.load(f"{BASE_URL}/{candidate}")
                    spec = extract_function_spec(page, candidate) if page is not None else None
                    if spec is not None and spec.get("type") is not None:
                        spec = {k: v for k, v in spec.items() if k != "examples"}
                        functions[spec["name"]] = spec
                        print(f"OK ({spec['type']}, /{candidate})")
                        break
                else:
                    print("MISSING")
                    function_failures.append(name)
    finally:
        fetcher.close()

    # Phase 2a: how the pages were read, and every HTTP failure.  A 404 on
    # a page that used to exist and a network timeout both end up here
    # rather than only in the failure counts below.
    print("\n=== Phase 2a: transport ===")
    report_transport(fetcher)

    # Phase 2c: usage-mode coverage (warning only — see report_usage_coverage).
    print("\n=== Phase 2c: usage mode coverage ===")
    complete = report_usage_coverage(functions)

    # Phase 2d: coverage of every field added on top of the original
    # contract.  A scraper rots by extracting less than it used to, so the
    # counts are printed on every run rather than only when something
    # fails outright.
    print("\n=== Phase 2d: added field coverage ===")
    complete &= report_added_field_coverage(functions, categories)

    protocol = derive_protocol_facts(structures)
    print("\n=== Phase 2e: structure pages + derived constants ===")
    complete &= report_structure_coverage(structures, protocol)

    # Phase 3: invert per-category tables into the feature → categories index
    # (see build_used_in_categories() for why this is authoritative).
    print("\n=== Phase 3: build feature → category inverse index ===")
    used_in = build_used_in_categories(categories)
    orphans_in_catalog: list[str] = []
    for feat_name, feat_spec in functions.items():
        feat_spec["used_in_categories"] = used_in.get(feat_name, [])
    # Features that appear in category tables but have no catalog page are
    # surfaced as a warning — usually harmless (Sber adds the row before
    # publishing the per-function page) but worth flagging so it doesn't
    # go unnoticed.
    for feat_name in sorted(used_in):
        if feat_name not in functions:
            orphans_in_catalog.append(feat_name)
    if orphans_in_catalog:
        print(f"WARNING: {len(orphans_in_catalog)} feature(s) used by categories but missing from /functions catalog:")
        for feat in orphans_in_catalog:
            print(f"  ? {feat}  used_in={used_in[feat]}")
    else:
        print(f"OK: every feature used by categories has a catalog entry ({len(used_in)} features linked)")

    # Write per-category snapshot (backward-compatible with existing tests)
    _write_json(SCHEMAS_FILE, categories)
    print(f"\nWrote {len(categories)} category schemas to {SCHEMAS_FILE}")

    # Write unified full spec
    full_spec = {
        "generated_at": datetime.now(UTC).isoformat(),
        "source": BASE_URL,
        "categories": categories,
        "functions": functions,
        "structures": structures,
        "protocol": protocol,
    }
    _write_json(FULL_SPEC_FILE, full_spec)
    print(f"Wrote unified spec ({len(categories)} categories, {len(functions)} functions) to {FULL_SPEC_FILE}")

    if category_failures or function_failures or structure_failures:
        print()
        if category_failures:
            print(f"Failed categories ({len(category_failures)}): {', '.join(category_failures)}")
        if function_failures:
            print(f"Failed functions ({len(function_failures)}): {', '.join(function_failures[:10])}...")
        if structure_failures:
            print(f"Failed structure pages ({len(structure_failures)}): {', '.join(structure_failures)}")
        return EXIT_PAGES_FAILED
    if not complete:
        print(
            "\nThe snapshot was written, but the WARN lines above mean the scraper "
            "extracted less than the pages carry.  Reread them before trusting the diff."
        )
        return EXIT_EXTRACTION_DEGRADED
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
