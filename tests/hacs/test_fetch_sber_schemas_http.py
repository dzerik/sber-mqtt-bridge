"""Тесты HTTP-транспорта скрапера ``tools/fetch_sber_schemas.py``.

Скрапер читает developers.sber.ru обычным HTTP: сайт — Docusaurus с
серверным рендерингом, и весь ``<article>`` приходит в первом же ответе.
Раньше страницы открывались браузером, и ``innerText`` бесплатно давал
переводы строк, табы между ячейками таблицы и «съедал» мусорные байты
CMS. Теперь это делает :func:`inner_text` по разметке, и ошибки здесь
молчаливые: страница по-прежнему грузится, но «хранит состоя ние
устройства» перестаёт совпадать с эталонной формулировкой, ``usage_mode``
становится ``None``, а вниз по течению валидатор тихо перестаёт проверять
функцию.

Поэтому тесты ниже:

* фиксируют нормализацию текста на кусках реальной разметки — с мягкими
  переносами, ``<wbr>``, zero-width, неразрывными пробелами и литеральным
  ``\\x00``, который CMS Sber оставляет внутри слов;
* проверяют выбор транспорта и срабатывание фолбэка на playwright;
* проверяют ретраи и то, что 404 и сетевой сбой различимы.

Сеть не дёргается: HTML — сохранённые фрагменты, ``urlopen`` и ``sleep``
подменяются.
"""

from __future__ import annotations

import importlib.util
import sys
import urllib.error
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRAPER_PATH = REPO_ROOT / "tools" / "fetch_sber_schemas.py"


def _load_scraper_module(name: str = "_scraper_http"):
    """Загрузить скрапер как отдельный модуль.

    Импорт playwright в скрапере необязателен, подменять его больше не
    нужно — модуль обязан грузиться и без библиотеки.

    Args:
        name: Имя, под которым модуль регистрируется (свежая копия на
            каждый вызов, чтобы тесты не делили состояние).

    Returns:
        Загруженный модуль скрапера.
    """
    spec = importlib.util.spec_from_file_location(name, SCRAPER_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def scraper():
    """Модуль скрапера, загруженный один раз на файл тестов."""
    return _load_scraper_module()


# --- фрагменты реальной разметки -------------------------------------------

# Абзац со страницы light_colour_temp: у Sber в CMS внутри слова
# «состояние» стоит литеральный NUL — браузер его выбрасывает, наивный
# разбор оставляет и ломает classify_usage().
USAGE_PARAGRAPH = (
    '<p class="doc-p"><strong class="doc-strong">Способ использования:</strong>'
    " хранит состоя\x00ние устройства и может менять его.</p>"
)

# Заголовок функции + штамп «Обновлено»: React вставляет между текстовыми
# узлами HTML-комментарии, из-за которых «Обновлено» и дата — разные узлы.
PAGE_HEADER = (
    "<header><div>"
    '<h1 id="lightcolourtemp" class="doc-h1">light_colour_temp (температура цвета)</h1>'
    '<div id="date-update" data-pdf="hidden"><div class="sc-hOzowv">'
    "Обновлено<!-- --> <!-- -->4 апреля 2025</div></div>"
    "</div></header>"
)

# Ссылка с внешней иконкой: между словами стоит span с BOM, пробелом и
# svg-иконкой. Иконка занимает место, поэтому пробелы вокруг неё браузер
# сохраняет — «температурой<span>﻿ <svg/></span> освещения».
LINK_WITH_ICON = (
    '<p class="doc-p"><strong>Назначение:</strong> управляет '
    '<a class="doc-a" href="https://ru.wikipedia.org/wiki/x">цветовой температурой'
    '<span style="white-space:nowrap">﻿ <svg viewBox="0 0 16 16"><path d="M5 1"></path></svg>'
    "</span></a> освещения.</p>"
)

# Блок кода Docusaurus: перевод строки — это <br>, отступы — обычные
# пробелы внутри <pre>, подсветка режет строку на десяток <span>.
CODE_BLOCK = (
    '<pre tabindex="0" class="prism-code language-json"><code class="codeBlockLines">'
    '<span class="token-line"><span class="token punctuation">{</span><br></span>'
    '<span class="token-line"><span class="token plain">    </span>'
    '<span class="token property">&quot;key&quot;</span>'
    '<span class="token operator">:</span><span class="token plain"> </span>'
    '<span class="token string">&quot;light_colour_temp&quot;</span><br></span>'
    '<span class="token-line"><span class="token punctuation">}</span><br></span>'
    "</code></pre>"
    '<div class="buttonGroup"><button type="button" title="Копировать" class="copyButton">'
    '<span class="copyButtonIcons" aria-hidden="true"><svg width="18"><path d="M14 1"></path></svg>'
    "</span></button></div>"
)

# Таблица «Доступные функции устройства» со страницы sensor_air: она
# обёрнута в <div> и не является прямым sibling'ом заголовка.
FEATURES_TABLE = (
    '<h2 class="doc-h2" id="dostupnye-funktsii-ustroystva16">Доступные функции устройства'
    '<span class="anchor">﻿<a class="heading-copy-link" href="#x">'
    '<svg width="16"><path d="M8 2"></path></svg></a></span></h2>'
    '<p class="doc-p">У устройства есть обязательные функции: online, open_state. Кроме того, '
    "обязательно должен быть описан способ открытия: либо open_set, либо open_percentage, "
    "либо они оба.</p>"
    '<div class="tableWrapper"><div class="inner"><table class="table table--default">'
    "<thead><tr><th><strong>Функция</strong></th><th><strong>Обязательная?</strong></th>"
    "<th><strong>Описание</strong></th></tr></thead><tbody>"
    '<tr><td><a class="doc-a" href="/docs/ru/smarthome/c2c/online">online</a></td>'
    "<td>✔︎</td><td>Доступность устройства: офлайн или онлайн</td></tr>"
    '<tr><td><a class="doc-a" href="/docs/ru/smarthome/c2c/open_set">open_set</a></td>'
    "<td>✔︎*</td><td>Открывание устройства</td></tr>"
    '<tr><td><a class="doc-a" href="/docs/ru/smarthome/c2c/co2">co2</a></td>'
    "<td></td><td>Текущая концентрация CO<sub>2</sub></td></tr>"
    "</tbody></table></div></div>"
)

# Мобильное оглавление: до гидратации оно есть в разметке, но скрыто.
HIDDEN_TOC = (
    '<div class="tocCollapsible" style="display:none"><ul id="headings-nav">'
    '<li><a href="#a">Устройства с этой функцией</a></li></ul></div>'
)

FUNCTION_PAGE = (
    "<html><head><title>Функция light_colour_temp | Документация для разработчиков</title>"
    '<script>window.__DATA__={"a":1}</script><style>.x{color:red}</style></head><body>'
    "<main><article>"
    + HIDDEN_TOC
    + PAGE_HEADER
    + '<p class="doc-p"><strong class="doc-strong">Тип данных:</strong> INTEGER(0, 1000).</p>'
    + USAGE_PARAGRAPH
    + LINK_WITH_ICON
    + FEATURES_TABLE
    + CODE_BLOCK
    + "</article></main></body></html>"
)


class TestInnerText:
    """:func:`inner_text` повторяет ``innerText`` там, где от него зависит разбор."""

    def _text(self, scraper, html: str) -> str:
        return scraper.inner_text(scraper.parse_html(html))

    def test_tags_inside_a_word_do_not_split_it(self, scraper):
        """Разметка внутри слова не превращается в пробел.

        Замена тегов на пробелы дала бы «состоя ние устройства», и
        ``classify_usage`` перестал бы узнавать формулировку.
        """
        text = self._text(scraper, "<p>хранит состоя<span></span>ние устройства</p>")
        assert "состояние устройства" in text

    def test_nul_byte_from_cms_is_dropped(self, scraper):
        """Литеральный ``\\x00`` из CMS Sber выбрасывается, как в браузере."""
        text = self._text(scraper, USAGE_PARAGRAPH)
        assert "\x00" not in text
        assert "хранит состояние устройства и может менять его" in text

    def test_soft_hyphen_and_wbr_and_zero_width_do_not_split_words(self, scraper):
        """Мягкий перенос, ``<wbr>`` и zero-width не разрывают слово.

        Все три — подсказки переносчику, а не разделители: читатель видит
        одно слово, значит и регулярки ниже по течению должны увидеть
        одно слово.
        """
        text = self._text(scraper, "<p>устрой&shy;ства и состоя<wbr>ние, зна​чение</p>")
        assert text == "устройства и состояние, значение"

    def test_nbsp_survives_collapsing(self, scraper):
        """Неразрывный пробел не схлопывается — им занимается normalize_spaces."""
        text = self._text(scraper, "<p>менять его не\xa0может</p>")
        assert "не\xa0может" in text
        assert scraper.normalize_spaces(text) == "менять его не может"

    def test_usage_sentence_ends_at_a_line_break(self, scraper):
        """Абзацы разделены переводами строк.

        ``_USAGE_DECL_RE`` берёт ``[^\\n]+``: без переводов строк
        предложение «Способ использования» проглотило бы всю страницу.
        """
        page = scraper.HttpDocPage("test", FUNCTION_PAGE)
        usage, mode = scraper.extract_usage(page.article_text())
        assert usage == "хранит состояние устройства и может менять его."
        assert mode == scraper.USAGE_STATE_READ_WRITE

    def test_paragraphs_are_separated_by_a_blank_line(self, scraper):
        """Между абзацами — пустая строка, между обычными блоками — одна."""
        assert self._text(scraper, "<p>раз</p><p>два</p>") == "раз\n\nдва"
        assert self._text(scraper, "<div>раз</div><div>два</div>") == "раз\nдва"

    def test_br_becomes_a_line_break(self, scraper):
        """``<br>`` — перевод строки; на нём держатся блоки кода Docusaurus."""
        assert self._text(scraper, "<div>раз<br>два</div>") == "раз\nдва"

    def test_table_cells_are_separated_by_tabs(self, scraper):
        """Ячейки разделены табом, строки — переводом строки.

        ``_OBLIGATION_SENTENCE_RE`` исключает таб именно для того, чтобы
        предложение не перетекало из ячейки в ячейку.
        """
        text = self._text(
            scraper,
            "<table><tr><td>online</td><td>✔︎</td></tr><tr><td>co2</td><td></td></tr></table>",
        )
        assert text.splitlines()[0] == "online\t✔︎"
        assert "co2" in text.splitlines()[-1]

    def test_pre_keeps_indentation_and_line_breaks(self, scraper):
        """В ``<pre>`` пробелы сохраняются — иначе JSON-примеры не прочитать."""
        text = scraper.parse_html(CODE_BLOCK).find_first("pre").text
        assert text == '{\n    "key": "light_colour_temp"\n}\n'

    def test_hidden_and_script_content_is_not_text(self, scraper):
        """Скрытое, ``<script>`` и ``<style>`` в текст не попадают."""
        text = self._text(
            scraper,
            '<div>видно</div><div style="display:none">скрыто</div>'
            "<div hidden>тоже скрыто</div><script>var x=1</script><style>.a{}</style>",
        )
        assert text == "видно"

    def test_icon_between_two_spaces_keeps_both(self, scraper):
        """Иконка занимает место, поэтому пробелы вокруг неё не схлопываются.

        Регрессия «цветовой температурой  освещения»: если выбросить svg
        молча, два пробела станут одним и текст разойдётся с браузерным.
        """
        text = self._text(scraper, LINK_WITH_ICON)
        assert "цветовой температурой﻿  освещения." in text

    def test_lone_icon_does_not_open_a_line(self, scraper):
        """Кнопка «Копировать» состоит из иконок и не даёт пустой строки."""
        text = self._text(scraper, f"<div>раз</div>{CODE_BLOCK}<div>два</div>")
        assert "\n\n\n" not in text


class TestHttpDocPage:
    """Страница, разобранная из HTML, отвечает то же, что отвечал браузер."""

    @pytest.fixture
    def page(self, scraper):
        """Функциональная страница целиком."""
        return scraper.HttpDocPage("https://example.test/light-colour-temp", FUNCTION_PAGE)

    def test_title_is_collapsed_like_document_title(self, page):
        """``title()`` отдаёт ``<title>`` со схлопнутыми пробелами."""
        assert page.title() == "Функция light_colour_temp | Документация для разработчиков"

    def test_meta_reads_h1_and_update_stamp(self, page, scraper):
        """H1 и штамп «Обновлено» читаются несмотря на комментарии React."""
        meta = page.meta()
        assert meta["h1"] == "light_colour_temp (температура цвета)"
        assert scraper.extract_doc_updated(meta["date"]) == "4 апреля 2025"
        assert scraper.extract_title_ru(meta["h1"]) == "температура цвета"

    def test_pre_texts_are_parseable_json(self, page):
        """Блоки кода отдаются с отступами и переводами строк."""
        assert page.pre_texts() == ['{\n    "key": "light_colour_temp"\n}\n']

    def test_features_table_is_found_inside_a_wrapper_div(self, page):
        """Таблица найдена, хотя обёрнута в два ``<div>`` (случай sensor_air)."""
        rows = page.features_table_rows()
        assert [row["feature"] for row in rows] == ["online", "open_set", "co2"]

    def test_obligatory_and_conditional_markers_are_split(self, page):
        """``✔︎`` — строго обязательная, ``✔︎*`` — условная, пусто — необязательная."""
        rows = {row["feature"]: row for row in page.features_table_rows()}
        assert [rows["online"]["obligatory"], rows["online"]["conditional"]] == [True, False]
        assert [rows["open_set"]["obligatory"], rows["open_set"]["conditional"]] == [False, True]
        assert [rows["co2"]["obligatory"], rows["co2"]["conditional"]] == [False, False]

    def test_cell_markup_does_not_leak_into_the_description(self, page):
        """``CO<sub>2</sub>`` читается как «CO2», а не как «CO 2»."""
        rows = {row["feature"]: row for row in page.features_table_rows()}
        assert rows["co2"]["description"] == "Текущая концентрация CO2"

    def test_category_intro_stops_before_the_table(self, page):
        """Вводная проза берётся до таблицы: её ячейки — не проза."""
        intro = page.category_intro()
        assert "обязательно должен быть описан способ открытия" in intro
        assert "Доступность устройства" not in intro

    def test_intro_yields_the_any_of_group(self, page, scraper):
        """Правило «либо open_set, либо open_percentage» вычитывается из прозы."""
        groups, unresolved = scraper.extract_any_of_groups(
            page.category_intro(), {"online", "open_set", "open_percentage", "open_state"}
        )
        assert groups == [["open_percentage", "open_set"]]
        assert unresolved == []

    def test_all_tables_includes_header_row(self, page):
        """``all_tables`` отдаёт и заголовок — по нему ищутся колонки."""
        tables = page.all_tables()
        assert tables[0][0] == ["Функция", "Обязательная?", "Описание"]

    def test_c2c_hrefs_are_returned_verbatim(self, page):
        """Ссылки отдаются как в разметке — из них собираются слаги."""
        assert page.c2c_hrefs() == [
            "/docs/ru/smarthome/c2c/online",
            "/docs/ru/smarthome/c2c/open_set",
            "/docs/ru/smarthome/c2c/co2",
        ]

    def test_missing_nodes_degrade_to_empty(self, scraper):
        """Пустая страница не роняет разбор, а отдаёт пустые значения."""
        page = scraper.HttpDocPage("https://example.test/x", "<html><body></body></html>")
        assert page.title() == ""
        assert page.article_text() == ""
        assert page.pre_texts() == []
        assert page.meta() == {"h1": "", "date": ""}
        assert page.features_table_rows() == []
        assert page.category_intro() == ""
        assert page.all_tables() == []
        assert page.c2c_hrefs() == []


class _FakeResponse:
    """Минимальный ответ ``urlopen`` — контекстный менеджер с ``read()``."""

    def __init__(self, body: bytes, status: int = 200) -> None:
        self.body = body
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self) -> bytes:
        return self.body


class TestFetchHtml:
    """Ретраи и различимость ошибок в :func:`fetch_html`."""

    def test_successful_fetch_returns_body(self, scraper):
        """Успешный ответ отдаёт декодированное тело и статус."""
        result = scraper.fetch_html(
            "https://example.test/a",
            urlopen=lambda *a, **k: _FakeResponse("привет".encode()),
            sleep=lambda _: None,
        )
        assert result.ok
        assert result.html == "привет"
        assert result.status == 200
        assert result.error is None

    def test_network_error_is_retried_and_can_succeed(self, scraper):
        """Разовый таймаут — не повод объявлять страницу пропавшей.

        На живом проходе так отваливались единичные страницы из 269, и
        без повтора это выглядело бы как «Sber удалил функцию».
        """
        calls = []
        pauses = []

        def urlopen(*_args, **_kwargs):
            calls.append(1)
            if len(calls) == 1:
                raise urllib.error.URLError("timed out")
            return _FakeResponse(b"ok")

        result = scraper.fetch_html("https://example.test/a", urlopen=urlopen, sleep=pauses.append)
        assert result.ok
        assert len(calls) == 2
        assert pauses == [scraper.HTTP_RETRY_PAUSE]

    def test_pause_grows_with_each_attempt(self, scraper):
        """Пауза растёт с номером попытки — мы в гостях у чужого сайта."""
        pauses = []

        def urlopen(*_args, **_kwargs):
            raise urllib.error.URLError("down")

        result = scraper.fetch_html("https://example.test/a", urlopen=urlopen, sleep=pauses.append)
        assert not result.ok
        assert pauses == [scraper.HTTP_RETRY_PAUSE, scraper.HTTP_RETRY_PAUSE * 2]
        assert "URLError" in (result.error or "")

    def test_404_is_not_retried_and_is_reported_as_such(self, scraper):
        """404 — это ответ, а не сбой: повторять нечего, но сказать надо.

        404 на известной странице и обрыв сети требуют разных действий,
        поэтому они и выглядят по-разному в отчёте.
        """
        calls = []

        def urlopen(*_args, **_kwargs):
            calls.append(1)
            raise urllib.error.HTTPError("https://example.test/a", 404, "Not Found", {}, None)

        result = scraper.fetch_html("https://example.test/a", urlopen=urlopen, sleep=lambda _: None)
        assert len(calls) == 1
        assert result.status == 404
        assert "HTTP 404" in (result.error or "")
        assert result.html is None

    def test_transient_status_is_retried(self, scraper):
        """503 — временная беда, её повторяем."""
        calls = []

        def urlopen(*_args, **_kwargs):
            calls.append(1)
            if len(calls) < 3:
                raise urllib.error.HTTPError("https://example.test/a", 503, "Busy", {}, None)
            return _FakeResponse(b"ok")

        result = scraper.fetch_html("https://example.test/a", urlopen=urlopen, sleep=lambda _: None)
        assert result.ok
        assert len(calls) == 3

    def test_fetch_many_returns_every_url_once(self, scraper, monkeypatch):
        """Параллельная выборка не теряет и не дублирует адреса."""
        monkeypatch.setattr(
            scraper,
            "fetch_html",
            lambda url, **_kwargs: scraper.FetchResult(url, f"<p>{url}</p>", 200, None),
        )
        urls = [f"https://example.test/{i}" for i in range(20)] + ["https://example.test/0"]
        results = scraper.fetch_many(urls)
        assert len(results) == 20
        assert all(results[url].html == f"<p>{url}</p>" for url in results)

    def test_parallelism_stays_polite(self, scraper):
        """Одновременных запросов не больше :data:`HTTP_MAX_PARALLEL`."""
        assert scraper.HTTP_MAX_PARALLEL <= 8


class TestDocFetcher:
    """Выбор транспорта: HTTP по умолчанию, браузер — только когда иначе никак."""

    def _fetcher(self, scraper, monkeypatch, results: dict[str, object]):
        fetcher = scraper.DocFetcher()
        monkeypatch.setattr(
            scraper,
            "fetch_html",
            lambda url, **_kwargs: results[url],
        )
        return fetcher

    def test_http_page_is_used_when_the_article_is_there(self, scraper, monkeypatch):
        """Нормальная страница читается по HTTP, браузер не поднимается."""
        url = "https://example.test/light-colour-temp"
        fetcher = self._fetcher(scraper, monkeypatch, {url: scraper.FetchResult(url, FUNCTION_PAGE * 3, 200, None)})
        monkeypatch.setattr(fetcher, "_browser_page", lambda _url: pytest.fail("браузер не нужен"))
        page = fetcher.load(url)
        assert isinstance(page, scraper.HttpDocPage)
        assert fetcher.http_pages == 1
        assert fetcher.browser_pages == 0
        assert fetcher.http_errors == {}

    def test_empty_article_falls_back_to_the_browser(self, scraper, monkeypatch):
        """Пустой ``<article>`` — повод открыть браузер, а не писать пустоту.

        Если Docusaurus однажды переедет на клиентский рендеринг, молча
        записанный «пустой» снапшот удалит половину спецификации.
        """
        url = "https://example.test/empty"
        shell = "<html><body><main><article></article></main></body></html>"
        fetcher = self._fetcher(scraper, monkeypatch, {url: scraper.FetchResult(url, shell, 200, None)})
        sentinel = object()
        monkeypatch.setattr(fetcher, "_browser_page", lambda _url: sentinel)
        assert fetcher.load(url) is sentinel
        assert fetcher.browser_pages == 1
        assert fetcher.recovered == [url]
        assert "article too short" in fetcher.http_errors[url]

    def test_http_failure_falls_back_to_the_browser(self, scraper, monkeypatch):
        """Сбой HTTP тоже уходит в браузер, а причина запоминается."""
        url = "https://example.test/gone"
        fetcher = self._fetcher(scraper, monkeypatch, {url: scraper.FetchResult(url, None, 404, "HTTP 404 Not Found")})
        sentinel = object()
        monkeypatch.setattr(fetcher, "_browser_page", lambda _url: sentinel)
        assert fetcher.load(url) is sentinel
        assert fetcher.http_errors[url] == "HTTP 404 Not Found"

    def test_page_is_lost_when_both_transports_fail(self, scraper, monkeypatch):
        """Если не смог никто — страница пропущена, и это видно в ошибках."""
        url = "https://example.test/gone"
        fetcher = self._fetcher(scraper, monkeypatch, {url: scraper.FetchResult(url, None, None, "URLError: down")})
        monkeypatch.setattr(fetcher, "_browser_page", lambda _url: None)
        assert fetcher.load(url) is None
        assert fetcher.browser_pages == 0
        assert fetcher.recovered == []
        assert fetcher.http_errors[url] == "URLError: down"

    def test_prefetch_is_consumed_by_load(self, scraper, monkeypatch):
        """Предвыборка отдаётся из кэша: второй раз страница не запрашивается."""
        url = "https://example.test/light-colour-temp"
        calls = []

        def fetch_html(target, **_kwargs):
            calls.append(target)
            return scraper.FetchResult(target, FUNCTION_PAGE * 3, 200, None)

        monkeypatch.setattr(scraper, "fetch_html", fetch_html)
        fetcher = scraper.DocFetcher()
        fetcher.prefetch([url])
        assert fetcher.load(url) is not None
        assert calls == [url]

    def test_missing_playwright_does_not_crash_the_run(self, scraper, monkeypatch, capsys):
        """Без установленного playwright скрапер работает, пока работает HTTP.

        Модуль больше не выходит с ошибкой на импорте: браузер нужен
        только фолбэку, и его отсутствие должно быть сказано вслух, а не
        уронить весь обход.
        """
        monkeypatch.setattr(scraper, "sync_playwright", None)
        url = "https://example.test/gone"
        fetcher = self._fetcher(scraper, monkeypatch, {url: scraper.FetchResult(url, None, None, "URLError: down")})
        assert fetcher.load(url) is None
        assert "playwright is not installed" in capsys.readouterr().out

    def test_module_imports_without_playwright(self):
        """Скрапер импортируется, даже если playwright недоступен вовсе."""
        saved = {name: sys.modules.get(name) for name in ("playwright", "playwright.sync_api")}
        sys.modules["playwright"] = None
        sys.modules["playwright.sync_api"] = None
        try:
            module = _load_scraper_module("_scraper_no_playwright")
        finally:
            for name, value in saved.items():
                if value is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = value
        assert module.sync_playwright is None
        assert module.HttpDocPage("x", FUNCTION_PAGE).title().startswith("Функция light_colour_temp")

    def test_close_is_safe_without_a_browser(self, scraper):
        """``close()`` на обходе без браузера ничего не делает и не падает."""
        scraper.DocFetcher().close()


class TestReportTransport:
    """Отчёт о транспорте: ошибки HTTP видно даже когда браузер спас страницу."""

    def test_clean_run_reports_counts_only(self, scraper, capsys):
        """Без ошибок печатается одна строка со счётчиками."""
        fetcher = scraper.DocFetcher()
        fetcher.http_pages = 134
        scraper.report_transport(fetcher)
        out = capsys.readouterr().out
        assert "134 page(s) over HTTP" in out
        assert "WARNING" not in out

    def test_errors_are_printed_verbatim_with_their_outcome(self, scraper, capsys):
        """404 и сетевой сбой печатаются дословно и с исходом каждого."""
        fetcher = scraper.DocFetcher()
        fetcher.http_pages = 1
        fetcher.browser_pages = 1
        fetcher.http_errors = {
            "https://example.test/a": "HTTP 404 Not Found",
            "https://example.test/b": "URLError: timed out",
        }
        fetcher.recovered = ["https://example.test/b"]
        scraper.report_transport(fetcher)
        out = capsys.readouterr().out
        assert "HTTP 404 Not Found" in out
        assert "NOT recovered" in out
        assert "URLError: timed out" in out
        assert "recovered in the browser" in out


class TestMainJsSweep:
    """Обход манифеста ``main.js``: находки и — главное — причина отказа."""

    MAIN_JS_URL = "https://media.sberdevices.ru/bsm-docs/0.940.1/docs/assets/js/main.9779adbc.js"
    DEVICES_HTML = f'<html><body><script src="{MAIN_JS_URL}"></script></body></html>'

    def _responses(self, scraper, monkeypatch, mapping):
        monkeypatch.setattr(scraper, "fetch_html", lambda url, **_kwargs: mapping[url])

    def test_slugs_are_read_from_the_manifest(self, scraper, monkeypatch):
        """Кебабные слаги (структурные страницы) отбрасываются, остальные остаются."""
        bundle = (
            'x:"@site/docs/ru/smarthome/c2c/light.mdx",'
            'y:"@site/docs/ru/smarthome/c2c/sensor_air.mdx",'
            'z:"@site/docs/ru/smarthome/c2c/account-linking.mdx"'
        )
        self._responses(
            scraper,
            monkeypatch,
            {
                f"{scraper.BASE_URL}/devices": scraper.FetchResult("d", self.DEVICES_HTML, 200, None),
                self.MAIN_JS_URL: scraper.FetchResult(self.MAIN_JS_URL, bundle, 200, None),
            },
        )
        assert scraper.discover_slugs_via_main_js() == {"light", "sensor_air"}

    def test_unreachable_bundle_names_the_reason(self, scraper, monkeypatch, capsys):
        """Отказ ``media.sberdevices.ru`` печатается дословно, а не прячется.

        Что сломается у пользователя, если тест упадёт: сводка слагов
        молча пропадёт из прогона, и «Sber завёл новую функцию» станет
        неотличимо от «хост с бандлом на секунду отказал» — в журнале
        останется только «main.js unreachable» без единой подсказки.
        """
        self._responses(
            scraper,
            monkeypatch,
            {
                f"{scraper.BASE_URL}/devices": scraper.FetchResult("d", self.DEVICES_HTML, 200, None),
                self.MAIN_JS_URL: scraper.FetchResult(
                    self.MAIN_JS_URL, None, None, "URLError: <urlopen error [Errno 111] Connection refused>"
                ),
            },
        )
        assert scraper.discover_slugs_via_main_js() is None
        out = capsys.readouterr().out
        assert self.MAIN_JS_URL in out
        assert "Errno 111" in out

    def test_sweep_failure_is_only_a_warning(self, scraper, capsys):
        """Пропущенная сводка не роняет прогон: обход спецификации продолжается."""
        scraper.report_mainjs_drift(None, set())
        assert "main.js unreachable" in capsys.readouterr().out
