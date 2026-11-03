from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class KnowledgeHit:
    source_id: str
    title: str
    source_url: str | None
    effective_date: str | None
    text: str
    rank: float | None = None

    def public_dict(self) -> dict[str, Any]:
        return asdict(self)


class LocalKnowledgeBase:
    """Read-only Tennessee Tech retrieval with deterministic relevance gating."""

    # Query-language cues mapped to tokens expected in source IDs/titles.
    # These are deliberately small and auditable. They are not a semantic model.
    INTENT_GROUPS: dict[str, dict[str, set[str]]] = {
        "dining": {
            "query": {"food", "eat", "eating", "dining", "meal", "meals", "cafeteria", "restaurant", "hungry"},
            "source": {"dining", "meal", "food"},
            "negative": {"financialaid", "financial_aid", "coa", "cost_of_attendance", "tuition"},
        },
        "financial_aid": {
            "query": {"fafsa", "financial", "aid", "grant", "grants", "loan", "loans", "cost", "tuition", "fees"},
            "source": {"financial", "fafsa", "aid", "cost", "tuition", "fees", "scholarship"},
            "negative": {"dining", "parking", "recreation"},
        },
        "scholarships": {
            "query": {"scholarship", "scholarships"},
            "source": {"scholarship"},
            "negative": set(),
        },
        "admissions": {
            "query": {"admission", "admissions", "apply", "application", "undergraduate", "graduate", "international"},
            "source": {"admission", "undergrad", "graduate", "international"},
            "negative": set(),
        },
        "calendar": {
            "query": {"calendar", "semester", "term", "deadline", "holiday", "break", "classes"},
            "source": {"calendar", "registrar"},
            "negative": set(),
        },
        "parking": {
            "query": {"parking", "permit", "permits", "vehicle"},
            "source": {"parking"},
            "negative": set(),
        },
        "housing": {
            "query": {"housing", "dorm", "dorms", "residence", "roommate"},
            "source": {"housing", "residence"},
            "negative": set(),
        },
        "health": {
            "query": {"clinic", "health", "doctor", "medical", "sick"},
            "source": {"health"},
            "negative": {"counseling"},
        },
        "counseling": {
            "query": {"counseling", "counselling", "counselor", "therapist", "mental"},
            "source": {"counseling", "wellness"},
            "negative": set(),
        },
        "library": {
            "query": {"library", "book", "books", "study", "research"},
            "source": {"library"},
            "negative": set(),
        },
        "recreation": {
            "query": {"gym", "fitness", "recreation", "rec", "workout", "intramural"},
            "source": {"recreation"},
            "negative": set(),
        },
        "registrar": {
            "query": {"registrar", "transcript", "registration", "register", "records"},
            "source": {"registrar"},
            "negative": set(),
        },
        "tutoring": {
            "query": {"tutor", "tutoring", "tutors"},
            "source": {"tutoring"},
            "negative": set(),
        },
        "career": {
            "query": {"career", "resume", "internship", "internships", "job", "jobs"},
            "source": {"career"},
            "negative": set(),
        },
        "police": {
            "query": {"police", "security", "emergency"},
            "source": {"police"},
            "negative": set(),
        },
        "student_orgs": {
            "query": {"club", "clubs", "organization", "organizations", "org", "studentorgs"},
            "source": {"studentorg", "organization"},
            "negative": set(),
        },
        "academics": {
            "query": {"major", "majors", "college", "colleges", "school", "schools", "degree", "program", "programs"},
            "source": {"major", "academic", "college", "school"},
            "negative": set(),
        },
    }

    CAMPUS_ANCHORS = {
        "tennessee tech", "tennessee technological", "tntech", "ttu", "campus",
        "golden eagle", "ruc", "roaden university center", "tech express", "techexpress",
    }

    def __init__(self, cfg: dict[str, Any] | None, root: Path):
        self.cfg = dict(cfg or {})
        p = Path(str(self.cfg.get("database_path", "runtime/knowledge.sqlite3")))
        self.path = p if p.is_absolute() else (Path(root) / p).resolve()
        self.enabled = bool(self.cfg.get("enabled", True))
        self.top_k = int(self.cfg.get("top_k", 5))
        self.max_context_chars = int(self.cfg.get("max_context_chars", 6000))
        self.min_term_coverage = float(self.cfg.get("min_term_coverage", 0.34))
        self.candidate_multiplier = max(2, int(self.cfg.get("candidate_multiplier", 4)))

    def available(self) -> bool:
        return self.enabled and self.path.is_file()

    def status(self) -> dict[str, Any]:
        info: dict[str, Any] = {
            "enabled": self.enabled,
            "available": self.available(),
            "database_path": str(self.path),
            "documents": 0,
            "chunks": 0,
        }
        if not self.available():
            return info
        try:
            with sqlite3.connect(self.path) as db:
                info["documents"] = int(db.execute("SELECT COUNT(*) FROM documents").fetchone()[0])
                info["chunks"] = int(db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0])
        except Exception as exc:
            info["error"] = str(exc)
            info["available"] = False
        return info

    @staticmethod
    def _raw_terms(text: str) -> list[str]:
        return re.findall(r"[\w'-]{2,}", str(text).casefold(), flags=re.UNICODE)

    @classmethod
    def _intent_names(cls, text: str) -> list[str]:
        raw = set(cls._raw_terms(text))
        return [name for name, spec in cls.INTENT_GROUPS.items() if raw.intersection(spec["query"])]

    @classmethod
    def _has_campus_anchor(cls, text: str) -> bool:
        low = str(text).casefold()
        if any(anchor in low for anchor in cls.CAMPUS_ANCHORS):
            return True
        # A strong campus-service intent is enough because this knowledge base is
        # explicitly scoped to Tennessee Tech. General words like "food" alone
        # are not enough unless they appear in a campus-ish request.
        intents = cls._intent_names(text)
        context_words = {"where", "campus", "university", "school", "student", "office", "center", "centre", "tech"}
        raw = set(cls._raw_terms(text))
        return bool(intents and raw.intersection(context_words))

    @staticmethod
    def _query_terms(text: str) -> list[str]:
        terms = LocalKnowledgeBase._raw_terms(text)
        stop = {
            "the", "and", "for", "with", "that", "this", "what", "when", "where",
            "who", "why", "how", "can", "could", "would", "should", "are", "was",
            "were", "you", "your", "about", "from", "into", "does", "did", "have",
            "has", "had", "tell", "please", "me", "is", "it", "of", "to", "in",
            "on", "at", "a", "an", "see", "look", "looking", "image", "picture",
            "photo", "camera", "vision", "visual", "holding", "hold", "color", "colour",
            "show", "shown", "there", "here", "right", "now", "get", "want", "need",
            "something", "some", "any", "campus", "university", "tennessee", "tech", "ttu",
            # Identity/onboarding/small-talk words should never drag campus
            # contact pages into a name exchange such as "call me Tyler".
            "call", "called", "name", "remember", "remembered", "hello", "hi",
            "hey", "thanks", "thank", "sure", "okay", "sounds", "good", "back",
        }
        useful: list[str] = []
        for term in terms:
            if term in stop or term in useful:
                continue
            useful.append(term)
            if len(useful) >= 12:
                break
        return useful

    @classmethod
    def _expanded_terms(cls, text: str, query_terms: list[str]) -> list[str]:
        out = list(query_terms)
        for intent in cls._intent_names(text):
            for token in cls.INTENT_GROUPS[intent]["query"]:
                if token not in out:
                    out.append(token)
                if len(out) >= 20:
                    return out
        return out

    @staticmethod
    def _fts_query_from_terms(terms: list[str]) -> str:
        return " OR ".join('"' + term.replace('"', '""') + '"' for term in terms)

    @classmethod
    def _fts_query(cls, text: str) -> str:
        terms = cls._query_terms(text)
        return cls._fts_query_from_terms(cls._expanded_terms(text, terms))

    def query_diagnostics(self, query: str) -> dict[str, Any]:
        terms = self._query_terms(query)
        intents = self._intent_names(query)
        attempted = bool(self.available() and terms and self._has_campus_anchor(query))
        return {"attempted": attempted, "query_terms": terms, "intents": intents}

    def _relevant(self, hit: KnowledgeHit, query_terms: list[str]) -> bool:
        if not query_terms:
            return False
        haystack = f"{hit.source_id} {hit.title} {hit.text}".casefold()
        matched = [t for t in query_terms if re.search(r"(?<!\w)" + re.escape(t) + r"(?!\w)", haystack)]
        if not matched:
            return False
        if len(query_terms) == 1:
            return True
        return (len(matched) / len(query_terms)) >= self.min_term_coverage

    @classmethod
    def _intent_score(cls, hit: KnowledgeHit, intents: list[str]) -> float:
        if not intents:
            return 0.0
        meta = f"{hit.source_id} {hit.title}".casefold().replace("-", "_")
        score = 0.0
        for intent in intents:
            spec = cls.INTENT_GROUPS[intent]
            if any(token in meta for token in spec["source"]):
                score += 5.0
            if any(token in meta for token in spec["negative"]):
                score -= 6.0
        return score

    def retrieve(self, query: str, top_k: int | None = None) -> list[KnowledgeHit]:
        if not self.available():
            return []
        diag = self.query_diagnostics(query)
        if not diag["attempted"]:
            return []
        query_terms = list(diag["query_terms"])
        expanded = self._expanded_terms(query, query_terms)
        fts = self._fts_query_from_terms(expanded)
        if not fts or not query_terms:
            return []
        limit = max(1, int(top_k or self.top_k))
        candidate_limit = max(limit * self.candidate_multiplier, 12)
        try:
            with sqlite3.connect(self.path) as db:
                db.row_factory = sqlite3.Row
                rows = db.execute(
                    """
                    SELECT d.source_id, d.title, d.source_url, d.effective_date,
                           c.text, bm25(chunks_fts) AS rank
                    FROM chunks_fts
                    JOIN chunks c ON c.id = chunks_fts.rowid
                    JOIN documents d ON d.id = c.document_id
                    WHERE chunks_fts MATCH ?
                    ORDER BY rank
                    LIMIT ?
                    """,
                    (fts, candidate_limit),
                ).fetchall()
        except sqlite3.OperationalError:
            return []
        hits = [
            KnowledgeHit(
                source_id=str(r["source_id"]),
                title=str(r["title"] or r["source_id"]),
                source_url=str(r["source_url"]) if r["source_url"] else None,
                effective_date=str(r["effective_date"]) if r["effective_date"] else None,
                text=str(r["text"]),
                rank=float(r["rank"]) if r["rank"] is not None else None,
            )
            for r in rows
        ]
        intents = list(diag["intents"])
        # A domain-matching source can be relevant even when it uses a synonym
        # rather than the user's exact word (e.g. "food" -> "meal plans").
        relevant = [
            hit for hit in hits
            if self._relevant(hit, query_terms) or self._intent_score(hit, intents) > 0
        ]
        relevant.sort(key=lambda h: (-self._intent_score(h, intents), float(h.rank or 0.0)))
        # When a clear intent exists and matching domain documents are present,
        # keep those domain matches only. This intentionally favors precision
        # over recall so unrelated campus pages cannot pollute the LLM prompt.
        if intents and any(self._intent_score(h, intents) > 0 for h in relevant):
            relevant = [h for h in relevant if self._intent_score(h, intents) > 0]
        return relevant[:limit]

    def format_context(self, hits: list[KnowledgeHit]) -> str:
        if not hits:
            return ""
        parts = [
            "LOCAL KNOWLEDGE BASE CONTEXT\n"
            "Use these curated offline excerpts for institution-specific facts. "
            "Prefer them over pretrained memory. Do not invent facts that are not supported. "
            "If the excerpts appear stale, conflicting, or incomplete, say so."
        ]
        used = len(parts[0])
        for hit in hits:
            meta = f"[Source: {hit.source_id} | {hit.title}"
            if hit.effective_date:
                meta += f" | effective {hit.effective_date}"
            if hit.source_url:
                meta += f" | {hit.source_url}"
            meta += "]"
            block = f"{meta}\n{hit.text.strip()}"
            if used + len(block) > self.max_context_chars:
                break
            parts.append(block)
            used += len(block)
        return "\n\n".join(parts)
