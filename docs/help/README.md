# Help Maintenance

Bundled Help is generated from the maintained Markdown sources below.

## Canonical Sources

- `docs/cli/USER_GUIDE.md`
- `docs/cli/USER_GUIDE.zh-TW.md`
- `docs/webui/USER_GUIDE.md`
- `docs/webui/USER_GUIDE.zh-TW.md`
- `docs/core/supported-models.md`
- `docs/core/supported-models.zh-TW.md`

Shared presentation sources are `docs/help/template.html` and
`docs/help/help.css`. The generator is `scripts/generate_help.py`.

The generator emits the complete canonical Help set in one run: CLI guide
pages, WebUI guide pages, both locales, both Supported Models pages, and shared
Help CSS. It does not generate only one runtime surface.

The CLI runtime owns its CLI guide pages, Supported Models pages, and shared
Help CSS under `src/powers_tool_cli/help/`. The WebUI runtime owns its WebUI
guide pages, Supported Models pages, and shared Help CSS under
`src/powers_tool_webui/static/help/`.

Generate into a temporary directory, then synchronize only the generated files
owned by the affected runtime surface(s). Do not manually edit generated Help
HTML.

Focused checks include
[`test_help_generator.py`](../../tests/tooling/test_help_generator.py),
[`test_cli_user_guide.py`](../../tests/cli/test_cli_user_guide.py), and
[`test_webui_help.py`](../../tests/webui/test_webui_help.py).
