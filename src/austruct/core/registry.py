"""Module register.

Governance minimum from the roadmap: *"Register of every module: type, owner,
checker, envelope, last vector run"*, plus *"Quarterly review: what got used,
what didn't, what broke"*.

Keeping the register in code rather than in a spreadsheet means it cannot drift
from the modules it describes -- a module registers itself at import, so the
register is generated from reality rather than maintained alongside it.

Usage::

    from austruct.core.registry import REGISTRY
    REGISTRY.summary()          # printable table for the quarterly review
    REGISTRY.unverified()       # what is blocking catalog entry
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .provenance import (
    ASET_COMPONENT_NAMES,
    ASETComponent,
    ModuleType,
    Provenance,
    VerificationStatus,
)


@dataclass
class RegistryEntry:
    """One module's register row."""

    provenance: Provenance
    envelope_summary: str = ""
    description: str = ""

    @property
    def key(self) -> str:
        return self.provenance.module


@dataclass
class ModuleRegistry:
    """In-process register of every calculation module that has been imported."""

    entries: dict[str, RegistryEntry] = field(default_factory=dict)

    def register(
        self,
        provenance: Provenance,
        description: str = "",
        envelope_summary: str = "",
    ) -> Provenance:
        """Add a module to the register. Returns the provenance unchanged.

        Called at module import so that registration cannot be forgotten::

            PROVENANCE = REGISTRY.register(
                Provenance(module=__name__, version="0.1.0", author="..."),
                description="AS 3600 flexural capacity of an RC section",
            )
        """
        self.entries[provenance.module] = RegistryEntry(
            provenance=provenance,
            description=description,
            envelope_summary=envelope_summary,
        )
        return provenance

    def by_status(self, status: VerificationStatus) -> list[RegistryEntry]:
        return [e for e in self.entries.values() if e.provenance.status is status]

    def by_type(self, module_type: ModuleType) -> list[RegistryEntry]:
        return [e for e in self.entries.values() if e.provenance.module_type is module_type]

    def by_component(self, component: ASETComponent) -> list[RegistryEntry]:
        """Modules belonging to one ASET component."""
        return [e for e in self.entries.values() if e.provenance.component is component]

    def coverage(self) -> str:
        """Build-out across the six ASET components.

        Answers "what have we actually got?", as distinct from
        :meth:`summary`, which answers "what have we verified?". The framework
        is only actionable if you can see which components are thin.
        """
        lines = ["ASET component coverage", "-" * 52]
        for component in (
            ASETComponent.REFERENCE_DATA,
            ASETComponent.PROJECT_DATA,
            ASETComponent.DEMAND,
            ASETComponent.DESIGN_DOCUMENTATION,
            ASETComponent.VERIFICATION,
            ASETComponent.REPORTING,
            ASETComponent.INFRASTRUCTURE,
        ):
            entries = self.by_component(component)
            name = ASET_COMPONENT_NAMES[component]
            label = f"{component.value}. {name}" if component.value != "0" else name
            marker = "--" if not entries else f"{len(entries):2d}"
            lines.append(f"  [{marker}]  {label}")
            for entry in sorted(entries, key=lambda e: e.key):
                lines.append(f"          {entry.key.replace('austruct.', '')}")
        return "\n".join(lines)

    def unverified(self) -> list[RegistryEntry]:
        """Modules not yet cleared for issue -- the catalog entry blocklist."""
        return [e for e in self.entries.values() if not e.provenance.issuable]

    def summary(self) -> str:
        """Register as a fixed-width table, for the quarterly review."""
        if not self.entries:
            return "Module register is empty."

        rows = []
        for entry in sorted(self.entries.values(), key=lambda e: e.key):
            p = entry.provenance
            rows.append(
                (
                    p.module.replace("austruct.", ""),
                    p.version,
                    p.module_type.value,
                    p.status.value,
                    p.checker or "-",
                    str(len(p.vectors)),
                )
            )

        headers = ("Module", "Ver", "Type", "Status", "Checker", "Vectors")
        widths = [
            max(len(headers[i]), max(len(r[i]) for r in rows)) for i in range(len(headers))
        ]
        line = "  ".join("-" * w for w in widths)
        out = ["  ".join(h.ljust(w) for h, w in zip(headers, widths)), line]
        out.extend("  ".join(c.ljust(w) for c, w in zip(r, widths)) for r in rows)
        out.append(line)
        n_unverified = len(self.unverified())
        out.append(f"{len(rows)} module(s), {n_unverified} not cleared for issue.")
        return "\n".join(out)


# Process-wide register. One per process is correct here -- it mirrors "the
# catalog", of which there is one.
REGISTRY = ModuleRegistry()
