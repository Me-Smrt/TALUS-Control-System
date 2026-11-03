from __future__ import annotations

"""Optional engineering-only FTS5 corpus and deterministic terminology correction."""

import re
from pathlib import Path
from typing import Any
from .knowledge import LocalKnowledgeBase

TECH_TERMS = ('resistor', 'resistance', 'circuit', 'electronics', 'electrical',
              'impedance', 'capacitor', 'inductor', 'motor', 'microcontroller',
              'kinematic', 'kinematics', 'robotics', 'servo', 'transistor',
              'damping', 'control system', 'kirchhoff', 'nodal', 'mesh', 'voltage',
              'current', 'thevenin', 'norton', 'wye', 'delta', 'star network')


def wye_delta_reference(question: str) -> str:
    normalized = question.casefold().replace('δ', 'delta').replace('Δ', 'delta').replace('△', 'delta')
    if not (re.search(r'\bwye\b|\bdelta\b|\bstar\b|\by\s*[-–/]\s*delta\b', normalized)
            and any(term in normalized for term in ('transform', 'resist', 'network', 'circuit', 'convert'))):
        return ''
    return ("[Deterministic electrical engineering terminology]\n"
            "In resistor networks, wye (Y/star) and delta (triangle) are reciprocal three-terminal transformations, "
            "not spherical coordinates or calculus substitutions. Label delta sides R_AB, R_BC, R_CA, "
            "and wye branches R_A, R_B, R_C from terminals A, B, C to the center. "
            "Delta → wye: R_A=R_AB*R_CA/S, R_B=R_AB*R_BC/S, R_C=R_BC*R_CA/S, "
            "where S=R_AB+R_BC+R_CA. "
            "Wye → delta: R_AB=P/R_C, R_BC=P/R_A, R_CA=P/R_B, "
            "where P=R_A*R_B+R_B*R_C+R_C*R_A. "
            "Check terminal labels and units explicitly; these formulas apply to resistances "
            "or generalized impedances under matching linear-network assumptions. "
            "For ambiguous problems ask the user to specify the resistor/terminal mapping.")


class EngineeringKnowledgeBase(LocalKnowledgeBase):
    """Engineering retrieval kept separate from campus-specific accuracy policy."""

    def __init__(self, cfg: dict[str, Any] | None, root: Path):
        super().__init__(cfg or {'database_path': 'runtime/engineering.sqlite3'}, root)

    def query_diagnostics(self, query: str) -> dict[str, Any]:
        terms = self._query_terms(query)
        low = query.casefold().replace('Δ', 'delta').replace('δ', 'delta')
        scoped = any(term in low for term in TECH_TERMS)
        return {'attempted': bool(self.available() and terms and scoped), 'query_terms': terms,
                'intents': [], 'domain': 'engineering'}

    def format_context(self, hits):
        if not hits:
            return ''
        context = super().format_context(hits)
        return context.replace('institution-specific facts', 'engineering reference facts').replace(
            'LOCAL KNOWLEDGE BASE CONTEXT', 'ENGINEERING CURATED KNOWLEDGE CONTEXT')
