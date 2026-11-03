# Curated technical references

This folder contains offline engineering references. Add verified, licensed `.md`, `.txt`, `.html`, `.csv`, or `.json` documents here, optionally with source URL / publication metadata sidecars. Do not assume generated model prose is an authoritative engineering source.

From the AUX project root, rebuild the engineering-specific FTS5 index (separate from the Tennessee Tech DB):

`python tools/build_knowledge_base.py --source-dir knowledge/engineering --db runtime/engineering.sqlite3`

The separate corpus is retrieved only for an engineering-anchored query. On a missing index, the system still applies its deterministic Y–Δ terminology/formula reference. Adding documents does not imply web access or automatically fetch anything.
