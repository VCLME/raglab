# Working with Claude on raglab

Short house rules for Claude sessions on this repo. Re-read this file at the
start of every session.

## Attribution footers

Do **not** add Claude-attribution footers to any artefact that ships with the
repo or with the change. In particular:

- PR titles and bodies
- Commit messages
- Code comments, docstrings
- README / docs / changelog entries

This includes lines like `🤖 Generated with Claude Code` and
`Co-Authored-By: Claude ...`.

If a tool or template adds one automatically, strip it before submitting.

## Tone

French for user-facing copy (UI labels, i18n French locale). English for
commit messages, PR bodies, code comments, and test names. Keep commit
subjects in the imperative and under ~72 characters; PR bodies may use a
Summary / Test plan structure.

## Scope control

One PR = one coherent change. When you notice out-of-scope issues during a
change (dead code, stale docs, obvious bug in unrelated file), flag them
with `mcp__ccd_session__spawn_task` rather than folding them in.

## Production track (roadmap phase 9)

raglab is being hardened phase by phase (9.1 to 9.8, see `docs/roadmap.md`).
Rules for that work:

- Every brick must show a measured gain on the frozen benchmarks (Recall@5/10,
  MRR, latency p50/p95, RAGAS judges). Follow `docs/benchmarks/protocole.md`:
  full haystack, seeded question sample, passage-level relevance
  (`expected_spans`). A brick that does not help stays behind a flag and is
  reported as such.
- One branch and one PR per sub-phase, with a before/after metrics table.
  Never merge without the owner's approval.
- Ask before adding a model larger than 1 GB, a new Docker service, or any DB
  schema change (Alembic migration required).
- Every retrieval option is exposed in CLI, API and UI (Retrieval page,
  expert mode, with intermediate scores).
- Never modify the `traditional`, `slide` and `late` chunkers: they are the
  comparison baseline.
- GPU budget: 8 GB. Ollama (qwen2.5:7b, generator) and llama.cpp models
  (question writer, RAGAS judge) never run at the same time. Use
  `raglab.llm.local_server.LocalLLMServer`, which unloads Ollama and
  starts/stops llama-server via `RAGLAB_LLAMACPP_START_COMMAND` /
  `RAGLAB_LLAMACPP_STOP_COMMAND`; the owner does not want to start servers by
  hand.
