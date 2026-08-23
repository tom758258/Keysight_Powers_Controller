import {
  LOCALE_STORAGE_KEY,
  SUPPORTED_LOCALES,
  getLocale,
  isSupportedLocale,
  setLocale,
  t,
} from "./i18n.js";

const initializedButtons = new WeakSet();

export function normalizeBrowserLanguage(value) {
  return typeof value === "string" ? value.trim().replaceAll("_", "-").toLowerCase() : "";
}

export function browserLocale(value) {
  const normalized = normalizeBrowserLanguage(value);
  if (
    normalized === "zh-tw"
    || normalized.startsWith("zh-tw-")
    || normalized === "zh-hant"
    || normalized.startsWith("zh-hant-")
  ) {
    return "zh-TW";
  }
  return "en";
}

export function detectBrowserLocale(navigatorObject) {
  let browserNavigator = navigatorObject;
  if (browserNavigator === undefined) {
    try {
      browserNavigator = globalThis.navigator;
    } catch (_error) {
      return "en";
    }
  }
  try {
    if (Array.isArray(browserNavigator?.languages)) {
      const language = browserNavigator.languages.find(
        (value) => typeof value === "string" && value.trim()
      );
      if (language) return browserLocale(language);
    }
  } catch (_error) {
    // Fall back to navigator.language when languages is unavailable.
  }
  try {
    if (typeof browserNavigator?.language === "string" && browserNavigator.language.trim()) {
      return browserLocale(browserNavigator.language);
    }
  } catch (_error) {
    // Browser locale access must not prevent WebUI initialization.
  }
  return "en";
}

export function readSavedLocale(storage) {
  try {
    const localeStorage = storage === undefined ? globalThis.localStorage : storage;
    const saved = localeStorage?.getItem(LOCALE_STORAGE_KEY);
    return isSupportedLocale(saved) ? saved : null;
  } catch (_error) {
    return null;
  }
}

export function resolveInitialLocale({
  storage,
  navigatorObject,
} = {}) {
  return readSavedLocale(storage) || detectBrowserLocale(navigatorObject);
}

export function persistLocale(locale, storage) {
  try {
    const localeStorage = storage === undefined ? globalThis.localStorage : storage;
    if (typeof localeStorage?.setItem !== "function") return false;
    localeStorage.setItem(LOCALE_STORAGE_KEY, locale);
    return true;
  } catch (_error) {
    return false;
  }
}

export function targetLocale(locale = getLocale()) {
  return SUPPORTED_LOCALES.find((candidate) => candidate !== locale) || "en";
}

export function renderLanguageButton(button, locale = getLocale()) {
  if (!button) return;
  const label = button.querySelector?.("#locale-toggle-label");
  if (!label) return;
  const target = targetLocale(locale);
  const displayKey = locale === "zh-TW" ? "locale.display_zh_tw" : "locale.display_en";
  const destinationKey = target === "zh-TW"
    ? "accessibility.switch_language_to_zh_tw"
    : "accessibility.switch_language_to_en";
  label.setAttribute("data-i18n", displayKey);
  label.setAttribute("lang", locale);
  label.textContent = t(displayKey);
  button.setAttribute("data-i18n-aria-label", destinationKey);
  button.setAttribute("data-i18n-title", destinationKey);
  button.setAttribute("aria-label", t(destinationKey));
  button.setAttribute("title", t(destinationKey));
}

export function initializeLocaleUi({
  documentObject,
  navigatorObject,
  storage,
  refreshPresentation = () => {},
} = {}) {
  let localeDocument = documentObject;
  if (localeDocument === undefined) {
    try {
      localeDocument = globalThis.document;
    } catch (_error) {
      localeDocument = null;
    }
  }
  const button = localeDocument?.getElementById?.("locale-toggle");
  if (button && initializedButtons.has(button)) {
    renderLanguageButton(button);
    return getLocale();
  }

  const locale = resolveInitialLocale({ storage, navigatorObject });
  setLocale(locale);
  if (localeDocument?.documentElement) localeDocument.documentElement.lang = locale;
  renderLanguageButton(button, locale);

  if (button) {
    button.addEventListener("click", () => {
      const nextLocale = targetLocale();
      setLocale(nextLocale);
      if (localeDocument?.documentElement) localeDocument.documentElement.lang = nextLocale;
      renderLanguageButton(button, nextLocale);
      persistLocale(nextLocale, storage);
      refreshPresentation();
    });
    initializedButtons.add(button);
  }
  return locale;
}
