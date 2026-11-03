# Offline Local Knowledge Base

The Automaton uses **local retrieval-augmented generation (RAG)** rather than trying to bake Tennessee Tech facts into the LLM or stuff an entire database into every prompt.

This is the right fit for university information because the base Qwen model can remain general-purpose while a small, replaceable local corpus carries facts that change: office contacts, policies, academic resources, campus services, schedules, hours, program information, and similar material.

## Runtime behavior

The auxiliary service never crawls the web. `runtime/knowledge.sqlite3` is opened read-only for retrieval. Relevant excerpts are inserted into the LLM request only when FTS5 finds matches.

If the database is absent, ordinary conversation continues and the service reports `knowledge=database_missing`.

## Add information

Place curated material in `knowledge/sources/` as any of:

- `.md` / `.txt`
- saved `.html`
- `.json` containing `text` or `content`
- `.csv` with a `text` or `content` column

For a text/Markdown/HTML file you may add a sidecar such as `student_success.md.meta.json`:

```json
{
  "source_id": "ttu.student-success.2026-09",
  "title": "Tennessee Tech Student Success Center",
  "source_url": "https://www.tntech.edu/...",
  "effective_date": "2026-09-29"
}
```

Use an official Tennessee Tech URL and an effective/download date whenever possible. This metadata lets the robot admit when offline information may be stale instead of presenting it as live data.

## Build / rebuild

```powershell
python tools\build_knowledge_base.py
```

The build is deterministic and local. Rebuilding replaces `runtime/knowledge.sqlite3`; it does not download anything.

## Recommended Tennessee Tech workflow

1. Select authoritative `tntech.edu` pages/documents that cover the questions the robot should answer.
2. Save or export them into `knowledge/sources/` with source metadata.
3. Run the builder once.
4. Test representative questions in `python main.py --console`.
5. Refresh the source snapshot periodically and rebuild the DB.

For a later production pass, semantic embeddings can be added alongside FTS5 if lexical search proves insufficient. Starting with SQLite FTS5 is intentional: it is tiny, deterministic, cross-platform, has no additional model in memory, and is usually strong for names, offices, programs, policies, and campus terminology.
