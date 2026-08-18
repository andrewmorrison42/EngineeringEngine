"""Generate ``CATALOGUE.md`` directly from ``austruct.core.registry.REGISTRY``.

Every calculation module in this package registers itself at import time
(``REGISTRY.register(...)`` at module scope -- see ``core/registry.py``).
That means a catalogue built from ``REGISTRY.entries`` cannot drift from the
modules it describes the way a hand-maintained list can (and did -- see the
README's now-fixed "Not built yet" table, which went stale for several
sessions before someone noticed). The only way this file goes out of date is
if someone edits it by hand instead of re-running this script, which
``tests/unit/test_catalogue.py`` catches.

Usage
-----
    python scripts/generate_catalogue.py            # (re)write CATALOGUE.md
    python scripts/generate_catalogue.py --check     # exit 1 if it's stale

The script has to IMPORT every module under ``austruct`` first -- a module
that has never been imported has never run its module-level
``REGISTRY.register()`` call, so it simply isn't in the register yet.
Modules gated behind an optional extra (``[tools]``, ``[optimise]``) that
isn't installed are skipped, and the file says so, rather than the script
crashing for someone who only installed the core package.
"""

from __future__ import annotations

import argparse
import importlib
import pkgutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_PATH = REPO_ROOT / "CATALOGUE.md"


def _import_everything() -> list[tuple[str, str]]:
    """Import every module under ``austruct``, so every module-level
    ``REGISTRY.register()`` call actually runs. Returns ``(module, reason)``
    for anything that could not be imported."""
    import austruct

    skipped: list[tuple[str, str]] = []

    def on_error(name: str) -> None:
        skipped.append((name, str(sys.exc_info()[1])))

    for module_info in pkgutil.walk_packages(
        austruct.__path__, prefix="austruct.", onerror=on_error
    ):
        try:
            importlib.import_module(module_info.name)
        except Exception as exc:  # noqa: BLE001 -- deliberately broad, see module docstring
            skipped.append((module_info.name, str(exc)))

    return skipped


def _group_key(module_path: str) -> str:
    """``austruct.design.as3600.flexure`` -> ``design.as3600``;
    ``austruct.tools.gravity_wall.checks.bearing`` -> ``tools.gravity_wall``;
    ``austruct.core.contract`` -> ``core.contract`` (nothing to collapse)."""
    parts = module_path.removeprefix("austruct.").split(".")
    return ".".join(parts[:2]) if len(parts) > 2 else module_path.removeprefix("austruct.")


def build_catalogue() -> str:
    from austruct.core.provenance import ASETComponent
    from austruct.core.registry import REGISTRY

    skipped = _import_everything()

    infrastructure = []
    domain_groups: dict[str, list] = {}
    for entry in REGISTRY.entries.values():
        if entry.provenance.component is ASETComponent.INFRASTRUCTURE:
            infrastructure.append(entry)
        else:
            domain_groups.setdefault(_group_key(entry.provenance.module), []).append(entry)

    lines = [
        "# austruct capability catalogue",
        "",
        "GENERATED FILE -- do not hand-edit. Every row below is read directly "
        "out of `austruct.core.registry.REGISTRY` at the point every module in "
        "the package has been imported once, so this list is exactly what is "
        "actually built, not what someone remembered to write down. "
        "Regenerate with:",
        "",
        "```bash",
        "python scripts/generate_catalogue.py",
        "```",
        "",
        "For HOW to use a domain (worked examples, code samples, the reasoning "
        "behind a design choice), see the matching README section -- this file "
        "answers \"what exists\", the README answers \"how do I use it\".",
        "",
        "**Status** is a verification claim, not a completeness one: "
        "`UNVERIFIED` means written but not checked against an external "
        "source, and its output is not for issue -- see the README's "
        "\"What is verified, and what is not\" section before trusting a "
        "number from any row below.",
        "",
        "Not every importable module is a row here -- only ones that "
        "produce their own `CalcResult` register with `REGISTRY`. An "
        "orchestration layer that calls other registered modules rather "
        "than doing its own standard-referenced arithmetic (e.g. "
        "`tools.cantilever_wall.member_design`, which builds a section and "
        "calls the already-listed `design.as3600.flexure`/`shear`; or "
        "`austruct.study`, the domain-agnostic sweep engine, which never "
        "touches a standard at all) is deliberately absent -- look for what "
        "it CALLS in the table below instead.",
        "",
    ]

    total = len(REGISTRY.entries)
    n_unverified = len(REGISTRY.unverified())
    lines.append(f"**{total} modules registered, {n_unverified} not yet cleared for issue.**")
    lines.append("")

    lines.append("## Contents")
    lines.append("")
    for group in sorted(domain_groups):
        # GitHub's heading-anchor algorithm: lowercase, strip anything that
        # isn't a word character/space/hyphen, spaces -> hyphens. Module
        # names are already lowercase; the only character in a group name
        # that isn't a "word char" is the dot -- underscores survive as-is,
        # they must NOT be turned into hyphens here.
        anchor = group.replace(".", "")
        lines.append(f"- [{group}](#{anchor}) ({len(domain_groups[group])})")
    lines.append("- [Framework infrastructure](#framework-infrastructure) "
                 f"({len(infrastructure)})")
    lines.append("")
    lines.append("---")
    lines.append("")

    for group in sorted(domain_groups):
        lines.append(f"## {group}")
        lines.append("")
        lines.append("| Module | Description | Status | Vectors | Scope / envelope |")
        lines.append("|---|---|---|---|---|")
        for entry in sorted(domain_groups[group], key=lambda e: e.key):
            p = entry.provenance
            module_short = p.module.removeprefix("austruct.")
            description = entry.description or "-"
            envelope = entry.envelope_summary or "-"
            lines.append(
                f"| `{module_short}` | {description} | {p.status.value} "
                f"| {len(p.vectors)} | {envelope} |"
            )
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## Framework infrastructure")
    lines.append("")
    lines.append(
        "Not a calculation domain -- the cross-cutting contract (the module "
        "contract, provenance/registry itself) that lets components 1-6 "
        "exchange data. Listed separately so the table above stays "
        "\"things you can calculate\", not \"things that exist in the repo\"."
    )
    lines.append("")
    lines.append("| Module | Description |")
    lines.append("|---|---|")
    for entry in sorted(infrastructure, key=lambda e: e.key):
        module_short = entry.provenance.module.removeprefix("austruct.")
        lines.append(f"| `{module_short}` | {entry.description or '-'} |")
    lines.append("")

    if skipped:
        lines.append("---")
        lines.append("")
        lines.append(
            "## Not scanned (missing optional dependency)"
        )
        lines.append("")
        lines.append(
            "The following could not be imported when this file was "
            "generated -- most likely an optional extra "
            "(`pip install -e \".[tools]\"` / `\".[optimise]\"`) is not "
            "installed in the environment that ran the script. Anything "
            "listed here is simply ABSENT from the tables above, not "
            "reported as unverified."
        )
        lines.append("")
        for name, reason in sorted(skipped):
            lines.append(f"- `{name}`: {reason}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true",
        help="Exit 1 if CATALOGUE.md is stale instead of writing it.",
    )
    args = parser.parse_args()

    content = build_catalogue()

    if args.check:
        current = OUTPUT_PATH.read_text() if OUTPUT_PATH.exists() else ""
        if current != content:
            print(f"{OUTPUT_PATH} is stale -- run scripts/generate_catalogue.py", file=sys.stderr)
            return 1
        print(f"{OUTPUT_PATH} is up to date.")
        return 0

    OUTPUT_PATH.write_text(content)
    print(f"Wrote {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
