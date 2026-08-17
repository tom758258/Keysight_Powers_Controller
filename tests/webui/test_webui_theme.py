from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from _webui_shared import extract_js_function, read_static_texts


REPO_ROOT = Path(__file__).resolve().parents[2]
STATIC_DIR = REPO_ROOT / "src" / "powers_tool_webui" / "static"
NODE = shutil.which("node")


def _css_rule_body(styles: str, selector: str) -> str:
    match = re.search(
        rf"(?ms)^{re.escape(selector)}\s*\{{(?P<body>.*?)^\}}",
        styles,
    )
    assert match is not None, f"Missing CSS rule for {selector}"
    return match.group("body")


def test_theme_control_and_initial_render_bootstrap_are_present() -> None:
    index = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    theme_source = (STATIC_DIR / "theme_ui.js").read_text(encoding="utf-8")
    _html, app_source, styles = read_static_texts()

    assert 'id="theme-toggle"' in index
    assert 'id="theme-toggle-label"' in index
    assert 'data-i18n="theme.system"' in index
    assert 'aria-hidden="true"' in index
    assert index.index("document.cookie") < index.index("/static/styles.css")
    assert index.index("powers-tool.webui.theme") < index.index("/static/styles.css")
    assert "localStorage" not in theme_source
    assert ':root[data-theme="light"]' in styles
    assert "color-scheme: light;" in styles
    assert "--chart-axis:" in styles
    assert "--chart-line:" in styles
    assert "onThemeChanged?.();" in theme_source
    assert "onThemeChanged: drawTrend" in app_source

    draw_trend = extract_js_function(app_source, "drawTrend")
    assert 'getComputedStyle(document.documentElement)' in draw_trend
    assert 'getPropertyValue("--chart-axis")' in draw_trend
    assert 'getPropertyValue("--chart-line")' in draw_trend
    assert "#d7dee6" not in draw_trend
    assert "#1f7a8c" not in draw_trend

    light_tokens = _css_rule_body(styles, ":root")
    dark_tokens = _css_rule_body(styles, ':root[data-theme="dark"]')
    for token in (
        "--surface-status-pending",
        "--surface-status-success",
        "--surface-status-success-soft",
        "--surface-status-error",
        "--surface-status-error-soft",
        "--surface-status-neutral",
        "--disabled-ink",
    ):
        assert f"{token}:" in light_tokens
        assert f"{token}:" in dark_tokens

    for selector in (".basic-channel-card", ".live-card"):
        body = _css_rule_body(styles, selector)
        assert "var(--panel)" in body
        assert "var(--surface-subtle)" in body
        assert "#ffffff" not in body
        assert "#f7f9fb" not in body

    for selector, token in (
        (".basic-action-pending", "--surface-status-pending"),
        (".basic-action-success", "--surface-status-success"),
        (".basic-action-error", "--surface-status-error"),
        (".output-status.off", "--surface-status-neutral"),
    ):
        assert f"var({token})" in _css_rule_body(styles, selector)

    disabled_rule = _css_rule_body(styles, "button:disabled")
    assert "var(--surface-disabled)" in disabled_rule
    assert "var(--disabled-ink)" in disabled_rule
    assert "opacity: .42" not in disabled_rule

    no_hardware_disabled_rule = _css_rule_body(styles, ".no-hardware-control[disabled]")
    assert "var(--surface-disabled)" in no_hardware_disabled_rule
    assert "var(--disabled-ink)" in no_hardware_disabled_rule
    assert "opacity: .58" not in no_hardware_disabled_rule

    dark_foreground = styles[styles.index("/* ─── Dark-theme Foreground Readability") :]
    for selector in (
        ':root[data-theme="dark"] button.command-pill-button',
        ':root[data-theme="dark"] button.utility-icon-button',
        ':root[data-theme="dark"] .category-button:hover',
        ':root[data-theme="dark"] .trigger-list-tabs button[data-trigger-list-channel="1"]',
        ':root[data-theme="dark"] .monitor-toggle',
        ':root[data-theme="dark"] .basic-toggle[data-basic-output="2"]',
    ):
        assert selector in dark_foreground
    assert "var(--ink)" in dark_foreground
    assert "var(--muted)" in dark_foreground
    assert "var(--accent-strong)" in dark_foreground

    disabled_override = styles[styles.index("/* Keep specialized controls readable when disabled rules are applied.") :]
    assert "button#run:disabled" in disabled_override
    assert ".trigger-list-tabs button[data-trigger-list-channel]:disabled" in disabled_override
    assert "button.basic-toggle:disabled" in disabled_override
    assert "button.monitor-toggle:disabled" in disabled_override
    assert "var(--surface-disabled)" in disabled_override
    assert "var(--disabled-ink)" in disabled_override


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
