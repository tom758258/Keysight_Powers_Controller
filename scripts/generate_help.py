"""Generate the offline Help bundle from canonical Markdown sources."""

from __future__ import annotations

import argparse
import html
import re
import shutil
from pathlib import Path

import markdown
from markdown.extensions.toc import TocExtension, slugify_unicode


REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_PATH = REPO_ROOT / "docs" / "help" / "template.html"
CSS_SOURCE_PATH = REPO_ROOT / "docs" / "help" / "help.css"

SOURCES = (
    ("docs/cli/USER_GUIDE.md", "cli.html", "en"),
    ("docs/cli/USER_GUIDE.zh-TW.md", "cli.zh-TW.html", "zh-TW"),
    ("docs/webui/USER_GUIDE.md", "webui.html", "en"),
    ("docs/webui/USER_GUIDE.zh-TW.md", "webui.zh-TW.html", "zh-TW"),
    ("docs/core/supported-models.md", "supported-models.html", "en"),
    (
        "docs/core/supported-models.zh-TW.md",
        "supported-models.zh-TW.html",
        "zh-TW",
    ),
)

LINK_TARGETS = {
    "../core/supported-models.md": "supported-models.html",
    "../core/supported-models.zh-TW.md": "supported-models.zh-TW.html",
}


def extract_h1_title(markdown_text: str) -> str:
    match = re.search(r"^# (.+)$", markdown_text, flags=re.MULTILINE)
    if not match:
        raise SystemExit("Error: no H1 title found in Help Markdown source.")
    return match.group(1).strip()


def rewrite_help_links(rendered_html: str) -> str:
    for source_path, output_name in LINK_TARGETS.items():
        rendered_html = rendered_html.replace(f'href="{source_path}', f'href="{output_name}')
    return rendered_html


def render_document(source_path: Path, lang: str, template: str) -> str:
    markdown_text = source_path.read_text(encoding="utf-8")
    title = html.escape(extract_h1_title(markdown_text), quote=True)
    content = markdown.markdown(
        markdown_text,
        extensions=[
            "fenced_code",
            "tables",
            "sane_lists",
            TocExtension(slugify=slugify_unicode),
        ],
    )
    content = rewrite_help_links(content)

    if template.count("{{lang}}") != 1 or template.count("{{title}}") != 1:
        raise SystemExit(
            "Error: template must contain {{lang}}, {{title}}, and "
            "{{content}} exactly once."
        )

    rendered = template.replace("{{lang}}", html.escape(lang, quote=True))
    rendered = rendered.replace("{{title}}", title)
    if "{{content}}" not in rendered:
        raise SystemExit(
            "Error: template must contain {{lang}}, {{title}}, and "
            "{{content}} exactly once."
        )
    rendered = rendered.replace("{{content}}", content)
    if "{{lang}}" in rendered or "{{title}}" in rendered or "{{content}}" in rendered:
        raise SystemExit(
            "Error: unexpanded template tokens remain in generated HTML."
        )
    return rendered


def generate(output_dir: Path) -> None:
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    token_counts = {token: template.count(token) for token in ("{{lang}}", "{{title}}", "{{content}}")}
    invalid_tokens = [token for token, count in token_counts.items() if count != 1]
    if invalid_tokens:
        raise SystemExit(
            f"Error: template tokens must appear exactly once; invalid: {invalid_tokens}."
        )

    output_dir.mkdir(parents=True, exist_ok=True)

    for relative_source, output_name, lang in SOURCES:
        source_path = REPO_ROOT / relative_source
        rendered = render_document(source_path, lang, template)
        (output_dir / output_name).write_text(rendered, encoding="utf-8")

    shutil.copyfile(CSS_SOURCE_PATH, output_dir / "help.css")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate the offline Help bundle from canonical sources."
    )
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()

    generate(args.output_dir.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
