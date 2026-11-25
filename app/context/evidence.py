"""Evidence storage, deliberate focus, and retrieval provenance."""
from dataclasses import dataclass, field
from typing import Any


@dataclass(kw_only=True)
class EvidenceState:
    evidence: dict[str, dict[str, Any]] = field(default_factory=dict)


    order: list[str] = field(default_factory=list)


    focus: list[str] = field(default_factory=list)


    retrieval_queries: dict[str, list[str]] = field(default_factory=dict)


    read_capture: dict[str, list[str]] | None = field(default=None, repr=False)


    def remember(self, rows: list[dict[str, Any]], query: str | None = None) -> None:
        for row in rows:
            short = str(row["id"])[:8]
            if short not in self.evidence:
                self.evidence[short] = row
                self.order.append(short)
            if self.read_capture is not None:
                self.read_capture["remembered"].append(str(row["id"]))
            if query:
                queries = self.retrieval_queries.setdefault(short, [])
                if query not in queries:
                    queries.append(query)


    def focus_on(self, rows: list[dict[str, Any]]) -> None:
        """Passages a tool read on purpose: these stay in front of the answer and the forced-answer digest."""
        for row in rows:
            short = str(row["id"])[:8]
            if short not in self.focus:
                self.focus.append(short)
            if self.read_capture is not None:
                self.read_capture["focused"].append(str(row["id"]))

