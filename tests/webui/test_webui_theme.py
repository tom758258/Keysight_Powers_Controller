from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from _webui_shared import read_static_texts


REPO_ROOT = Path(__file__).resolve().parents[2]
STATIC_DIR = REPO_ROOT / "src" / "powers_tool_webui" / "static"
NODE = shutil.which("node")


def test_theme_control_and_initial_render_bootstrap_are_present() -> None:
    index = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    theme_source = (STATIC_DIR / "theme_ui.js").read_text(encoding="utf-8")
    _html, app_source, _styles = read_static_texts()

    assert 'id="theme-toggle"' in index
    assert 'id="theme-toggle-label"' in index
    assert 'data-i18n="theme.system"' in index
    assert 'aria-hidden="true"' in index
    assert index.index("document.cookie") < index.index("/static/styles.css")
    assert index.index("powers-tool.webui.theme") < index.index("/static/styles.css")
    assert "onThemeChanged?.();" in theme_source
    assert "onThemeChanged: drawTrend" in app_source


def test_help_theme_bootstrap_and_desktop_query_contract() -> None:
    template = (REPO_ROOT / "docs" / "help" / "template.html").read_text(encoding="utf-8")
    help_css = (REPO_ROOT / "docs" / "help" / "help.css").read_text(encoding="utf-8")
    desktop = (REPO_ROOT / "desktop" / "main.cjs").read_text(encoding="utf-8")

    # Help bootstrap must run before help.css
    assert template.index("powers-tool.webui.theme") < template.index('href="help.css"')
    assert template.index("dataset.theme") < template.index('href="help.css"')
    assert "URLSearchParams" in template
    assert 'get("theme")' in template
    for value in ('"system"', '"light"', '"dark"'):
        assert value in template
    assert 'matchMedia("(prefers-color-scheme: dark)")' in template
    assert "addEventListener" in template and '"change"' in template
    # Preservation of explicit Desktop theme across Help-document navigation
    assert "preserveHelpThemeQuery" in template
    assert "?theme=" in template
    assert 'indexOf(".html")' in template
    assert 'getAttribute("href")' in template

    # Help CSS must use explicit data-theme dark selector, not sole media query
    assert ':root[data-theme="dark"]' in help_css
    assert ':root[data-theme="dark"] :not(pre) > code' in help_css
    assert ':root[data-theme="dark"] pre code' in help_css
    assert "@media (prefers-color-scheme: dark)" not in help_css

    # Desktop must carry validated theme via query when opening Help externally
    assert "nativeTheme.themeSource" in desktop
    assert "THEME_PREFERENCES.has" in desktop
    assert 'searchParams.set("theme"' in desktop
    assert "shell.openExternal(parsed.href" in desktop
    assert 'pathname.startsWith("/help/")' in desktop


@pytest.mark.skipif(NODE is None, reason="Node.js is required for theme runtime tests")
def test_theme_preference_runtime_behavior() -> None:
    script = r'''
import assert from "node:assert/strict";

const [themeUrl, i18nUrl] = process.argv.slice(1);
const theme = await import(themeUrl);
const i18n = await import(i18nUrl);

class FakeElement {
  constructor() {
    this.attributes = {};
    this.dataset = {};
    this.listeners = new Map();
    this.textContent = "";
  }
  addEventListener(name, listener) { this.listeners.set(name, listener); }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  click() { this.listeners.get("click")?.(); }
}

class CookieDocument {
  constructor(value = "", readFails = false, writeFails = false) {
    this.value = value;
    this.readFails = readFails;
    this.writeFails = writeFails;
    this.writes = [];
  }
  get cookie() {
    if (this.readFails) throw new Error("read failed");
    return this.value;
  }
  set cookie(value) {
    if (this.writeFails) throw new Error("write failed");
    this.writes.push(value);
    this.value = value.split(";", 1)[0];
  }
}

class MediaQuery {
  constructor(matches) { this.matches = matches; this.listener = null; }
  addEventListener(name, listener) {
    assert.equal(name, "change");
    this.listener = listener;
  }
  change(matches) { this.matches = matches; this.listener?.({ matches }); }
}

assert.deepEqual(theme.SUPPORTED_THEME_PREFERENCES, ["system", "light", "dark"]);
assert.equal(theme.nextThemePreference("system"), "light");
assert.equal(theme.nextThemePreference("light"), "dark");
assert.equal(theme.nextThemePreference("dark"), "system");
assert.equal(
  theme.readSavedThemePreference(
    new CookieDocument("other=value; powers-tool.webui.theme=dark; another=value")
  ),
  "dark",
);
assert.equal(theme.readSavedThemePreference(new CookieDocument("powers-tool.webui.theme=invalid")), null);
assert.equal(theme.readSavedThemePreference(new CookieDocument("", true)), null);
assert.equal(theme.effectiveTheme("system", new MediaQuery(false)), "light");
assert.equal(theme.effectiveTheme("system", new MediaQuery(true)), "dark");
assert.equal(theme.effectiveTheme("light", new MediaQuery(true)), "light");
assert.equal(theme.effectiveTheme("dark", new MediaQuery(false)), "dark");

const button = new FakeElement();
const label = new FakeElement();
const documentElement = new FakeElement();
const cookieDocument = new CookieDocument("powers-tool.webui.theme=dark");
const media = new MediaQuery(false);
let redraws = 0;
const ui = theme.initializeThemeUi({
  button,
  label,
  documentElement,
  cookieDocument,
  mediaQuery: media,
  onThemeChanged: () => { redraws += 1; },
});

assert.equal(ui.getPreference(), "dark");
assert.equal(documentElement.dataset.theme, "dark");
assert.equal(redraws, 1);
assert.equal(label.textContent, "Dark");
assert.equal(button.attributes["aria-label"], "Switch theme to System");
media.change(true);
assert.equal(documentElement.dataset.theme, "dark");
assert.equal(redraws, 1);

button.click();
assert.equal(ui.getPreference(), "system");
assert.equal(documentElement.dataset.theme, "dark");
assert.equal(redraws, 2);
const persistedCookie = cookieDocument.writes.at(-1);
assert.match(persistedCookie, /^powers-tool\.webui\.theme=system;/);
assert.match(persistedCookie, /(?:^|; )Max-Age=([1-9][0-9]*)(?:;|$)/);
assert.match(persistedCookie, /(?:^|; )Path=\/(?:;|$)/);
assert.match(persistedCookie, /(?:^|; )SameSite=Lax(?:;|$)/);
assert.doesNotMatch(persistedCookie, /(?:^|; )Domain=/i);
media.change(false);
assert.equal(documentElement.dataset.theme, "light");
assert.equal(redraws, 3);

button.click();
assert.equal(ui.getPreference(), "light");
media.change(true);
assert.equal(documentElement.dataset.theme, "light");
button.click();
assert.equal(ui.getPreference(), "dark");

i18n.setLocale("zh-TW");
ui.refresh();
assert.equal(label.textContent, "深色");
assert.equal(button.attributes.title, "切換主題至系統");

const fallbackDocument = new FakeElement();
const fallbackUi = theme.initializeThemeUi({
  button: new FakeElement(),
  label: new FakeElement(),
  documentElement: fallbackDocument,
  cookieDocument: new CookieDocument("powers-tool.webui.theme=invalid"),
  mediaQuery: new MediaQuery(true),
});
assert.equal(fallbackUi.getPreference(), "system");
assert.equal(fallbackDocument.dataset.theme, "dark");

const unsavedButton = new FakeElement();
const unsavedDocument = new FakeElement();
const unsavedUi = theme.initializeThemeUi({
  button: unsavedButton,
  label: new FakeElement(),
  documentElement: unsavedDocument,
  cookieDocument: new CookieDocument("", false, true),
  mediaQuery: new MediaQuery(false),
});
unsavedButton.click();
assert.equal(unsavedUi.getPreference(), "light");
assert.equal(unsavedDocument.dataset.theme, "light");

process.stdout.write(JSON.stringify({ ok: true }));
'''
    completed = subprocess.run(
        [
            NODE,
            "--input-type=module",
            "--eval",
            script,
            (STATIC_DIR / "theme_ui.js").resolve().as_uri(),
            (STATIC_DIR / "i18n.js").resolve().as_uri(),
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert completed.returncode == 0, (
        "Node theme preference contract failed\n"
        f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    )
    assert completed.stdout == '{"ok":true}'
