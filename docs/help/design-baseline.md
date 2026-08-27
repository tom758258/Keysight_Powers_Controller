# Help Design Baseline

## 1. Purpose

This document records the information architecture, editorial style,
boundary-writing patterns, terminology style, and existing presentation traits
observed in the current Powers Tool user guides. It is a developer and
maintainer reference for designing a shared Help presentation layer.

Markdown USER_GUIDE files are the content source. At the time this baseline
was recorded, legacy Traditional Chinese HTML mirrors were used as
presentation references. Those mirrors have since been retired after the
shared Help presentation replaced them. This baseline does not decide the
next template implementation, CSS specification, or generator design.

## 2. Source Material

- `docs/cli/USER_GUIDE.md`
- `docs/cli/USER_GUIDE.zh-TW.md`
- `docs/webui/USER_GUIDE.md`
- `docs/webui/USER_GUIDE.zh-TW.md`
- `docs/core/supported-models.md`
- `docs/core/supported-models.zh-TW.md`

The visual and interaction observations later in this baseline were captured
from legacy Traditional Chinese HTML mirrors that have since been removed.
Supported Models is evidence of the shared user-facing support dependency. It
is not the source of USER_GUIDE editorial or visual style.

## 3. Shared Information Architecture

The current guides follow an operator journey rather than a component or API
inventory:

- Introduce the audience and normal Product use before details.
- Put startup or entry-point instructions near the front.
- Put first-use and first-live workflows before advanced operations.
- Prefer safe read-only discovery before risky write or output actions.
- Group content by operator workflow, not by implementation module.
- Explain unsupported behavior and exact support boundaries next to the
  relevant workflow.
- Put troubleshooting and shared Product documentation near the end.
- Use Supported Models as the shared Product support authority.

Current structure is evidence for the design pattern, not a requirement that
future guides preserve the exact number, names, or order of sections.

## 4. CLI-Specific Architecture

The CLI guide is a workflow-first operator guide, not a complete command
reference. Its current flow moves from starting the executable through a safe
first live check, resource discovery and session variables, finite workflow
loops, model-specific serial operation, read-only checks, telemetry,
output-affecting actions, command orientation, no-hardware planning,
troubleshooting, and shared Product documentation.

Command-specific option details are delegated to
`powers-tool <command> --help`. The guide explains operator intent, safety
context, and support boundaries instead of duplicating a full option inventory.

This flow describes the current operator journey; it is not a required template
section list.

## 5. WebUI-Specific Architecture

The WebUI guide follows user-visible surfaces and workflows, not backend or API
module structure. Its current flow covers startup, the Desktop shell as a
release shell for the same WebUI, browser presentation controls, screen
overview, first use, resource scanning and identity evaluation, Live Data,
basic operations, advanced workflows, job results, stop/cancel behavior,
troubleshooting, safety notes, and shared documentation.

The Desktop shell belongs to the WebUI operator journey. It does not introduce
a separate documentation architecture.

## 6. Editorial Style

The current guides consistently use:

- operator-facing language;
- workflow-first organization;
- procedural steps with concrete commands or screen actions;
- safety-aware sequencing;
- explicit statements about what a result does and does not prove;
- low-assumption explanations;
- examples accompanied by context;
- planning/simulate/dry-run distinguished from live hardware;
- intentional fail-closed wording for unsupported combinations;
- no marketing language.

Risky output-affecting actions appear after the conditions that make them safe.

## 7. Boundary-Writing Patterns

The guides repeatedly express these boundaries:

- Diagnostic success does not imply Product support.
- `--model` and Expected model selections guard or plan requests; they do not
  unlock unsupported features.
- Frontend disabled state is guidance, not the final safety boundary.
- No-hardware identity does not imply live support.
- A supported family does not imply that every command or sub-feature is
  supported.
- Product LIVE support is exact by model, command, transport, backend, and
  required feature.
- Risky writes require stronger operator confirmation than read-only checks.
- Explicit resource selection is preferred over guessing.

These patterns describe how boundaries should be communicated; they do not
duplicate the complete prose from any guide.

## 8. Technical Terminology Style

Traditional Chinese text naturally retains established technical terms where
they aid precision and cross-document comparison, including Product, LIVE,
model, command, transport, backend, Product-open, fail closed, dry-run,
simulate, VISA, SCPI, WebUI, CLI, Expected model, and Live Data.

Machine-facing identifiers remain unchanged: canonical model IDs, command
names, CLI flags, VISA resource strings, deterministic SIM resources, SCPI
tokens, numeric limits, units, and manual references.

A future presentation layer must not translate or rewrite machine-facing
identifiers.

## 9. Existing Visual Baseline

Both legacy HTML mirrors previously used a light-oriented reading layout with a
left sticky table of contents on desktop, bounded main reading columns, a
system UI font stack, a blue primary accent, neutral slate surfaces, clear
H1/H2/H3 hierarchy, an H2 separator rule, bordered tables, inline code styling,
dark code blocks, and copy buttons.

Implementation references at baseline time differed by surface:

- Sidebar width: CLI about 290 px; WebUI about 280 px.
- Main column max-width: CLI about 1080 px; WebUI about 900 px.
- Tables: both are bordered. The CLI stylesheet explicitly provides horizontal
  table overflow. Do not claim that behavior as shared WebUI legacy behavior.
- Responsive breakpoints: CLI about 820 px; WebUI about 768 px.

These values are current implementation references, not immutable design tokens
or test contracts. Unifying them is a future Help presentation decision.

## 10. Existing Interaction Baseline

Shared extracted behavior includes automatic table-of-contents generation from
document headings, anchor navigation, active-section indication using
IntersectionObserver, copy buttons on code blocks, and responsive navigation
that moves out of the fixed desktop sidebar layout.

Current implementation differences include:

- The CLI TOC includes H2/H3 entries; the WebUI legacy TOC uses H2 entries.
- The CLI provides visible localized copy success/failure states.
- The WebUI provides localized copy success text but logs copy failure to the
  console.
- The CLI explicitly enables smooth scrolling; do not claim this as shared
  behavior.

These differences are current implementation evidence, not requirements that
the shared Help template preserve them.

## 11. Baseline Gaps / Future Decisions

At the time this baseline was recorded, the following items were gaps or
decisions for the next stage, not current shared behavior:

- The legacy Help stylesheet was primarily light-oriented. This is separate from
  the WebUI product theme controls described in its user guide.
- No shared Help template existed.
- No Markdown-to-Help-HTML pipeline existed.
- The CLI and WebUI legacy HTML bodies were separately maintained.
- Help-level language navigation was not currently a shared presentation
  primitive.
- Help version, footer, and branding structure were not currently standardized.

Dark mode, language switching UI, header/footer layout, icons, and JavaScript
architecture require separate future decisions.

## 12. Preserve vs. Do Not Freeze

### Preserve

- Workflow-first information architecture.
- Operator-facing tone.
- Safety and context before risky action.
- Exact support-boundary clarity.
- Supported Models as shared authority.
- Readable TOC.
- Code-copy usability.
- Responsive reading layout.
- Clear code and table treatment.

### Do Not Freeze

- Exact number of sections.
- Exact section names.
- Current prose.
- Exact pixel dimensions.
- Current color hex values.
- Current HTML markup.
- Current JavaScript implementation.
- Legacy HTML file structure observed at baseline time.
