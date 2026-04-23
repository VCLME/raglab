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
