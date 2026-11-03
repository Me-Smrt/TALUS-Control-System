# Tennessee Tech Offline Knowledge Snapshot

Snapshot date: 2026-09-29

This archive is a broad, assistant-oriented snapshot of public Tennessee Tech University information from official Tennessee Tech web sources. It is designed for the Automaton project's local RAG knowledge base.

It is **not a verbatim mirror of the university website**. The source documents are concise factual summaries with source URLs so the corpus remains compact, searchable, and respectful of source-site content. The archive focuses on information most useful to a campus assistant: institution background, academics, admissions, costs, aid, housing/dining/parking, student support, health/safety, technology, policies, and major campus contacts.

Dynamic information such as exact office hours, fees, deadlines, schedules, contacts, policies, housing availability, and current events can become stale. The system prompt should treat the snapshot date as a limit and say when it cannot establish that a time-sensitive answer is current.

## Install into the Auxiliary Processor project

Copy `knowledge/sources/` over the project's `knowledge/sources/` directory and either:

1. copy `runtime/knowledge.sqlite3` into the project's `runtime/` directory, or
2. rebuild locally with `python tools/build_knowledge_base.py`.

The `source_manifest.csv` and `.json` files list all included official source URLs.

Included source records: 39.


## Scope and provenance

Every knowledge document has a matching `.meta.json` sidecar containing its official source URL and snapshot date. `source_manifest.csv` and `source_manifest.json` provide the complete source inventory used for this snapshot. The corpus intentionally summarizes public pages rather than reproducing the Tennessee Tech website verbatim. It is broad for campus-assistant use, but it is not a guarantee that every public Tennessee Tech page or every rapidly changing fact on the site is represented.
