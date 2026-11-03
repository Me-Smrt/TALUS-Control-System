# Reasoning profiles and offline knowledge

## Hybrid reasoning

`llama-server` is launched with `--reasoning auto`. Each conversation request then chooses one of two profiles:

- **fast** — `reasoning_effort=none`, low-latency conversational output, 320-token default budget.
- **deep** — thinking enabled, larger 1400-token default budget and longer timeout.

The default routing mode is `auto`: ordinary conversation stays fast, while a deliberately conservative set of complex-analysis/debug/planning cues can select deep mode. Console commands always override the router:

```text
/think <question>   force deep reasoning
/fast <question>    force fast response
```

The API accepts `reasoning_mode: "auto" | "fast" | "deep"` on `/v1/conversation/text` and `/v1/vision/ask`.

Hidden model reasoning is never presented as the robot's answer. If a deep request takes several seconds, the conversation manager can emit configured hard-coded progress lines. The live audio loop voices those lines; `--console --speak` voices them during desktop testing.

## Offline knowledge

University facts should not be encoded permanently into the system prompt or trusted from the base model's training data. The project therefore uses a replaceable local RAG snapshot:

```text
curated source files -> tools/build_knowledge_base.py -> runtime/knowledge.sqlite3
                                                   -> SQLite FTS5 retrieval
                                                   -> only relevant excerpts enter the LLM prompt
```

See `knowledge/README.md` for the ingestion workflow.
