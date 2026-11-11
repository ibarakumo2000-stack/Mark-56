# Mark-LVII feature integration

This branch adds persistent background work and scheduled routines to Mark 56.

## Background tasks

The `background_tasks` action supports:
- `start`: queue work for the general or researcher agent, optionally scheduled for later
- `list` and `status`: inspect task progress
- `result`: retrieve the saved result/report
- `steer`: add an instruction to a running task
- `finish`: stop and write up the work completed so far
- `cancel`: stop without producing a report
- `agents`: list Markdown agent profiles

Each task stores its conversation checkpoints under `memory/tasks/`, and reports are written under `reports/`. These are runtime data directories and should not be committed.

The model adapter prefers Gemini REST tool-calling models and falls back to Mark 56's existing loopback-only Ollama adapter when local model mode is enabled. For the local fallback, the model must return the constrained JSON tool-call envelope; requested tool names are checked against the current agent's allowlist before execution.

## Deep research

The researcher agent plans subquestions, reads public pages in full, records findings, checks quoted passages against fetched page text, validates citations, and writes a report. It cannot access desktop-control or message-sending tools. Page fetching rejects private/local network destinations and validates redirects.

## Routines

The `routines` action supports one-off and recurring time rules, weekly/monthly schedules, every-N-minute schedules, startup/idle triggers, manual run, update, remove, and quiet hours. User-created routines are persisted in `memory/routines.json`.

Mark 56 already owns its morning briefing, proactive check-ins, and monitored-topic alerts. The integration deliberately does not seed duplicate versions of those services.

## Data and safety

- Task working files are confined to each task's own folder.
- Agent profiles are plain Markdown files in `agents/`.
- Task reports and runtime state are local data, not source-controlled configuration.
- The existing Mark 56 screen-agent safety rules and human confirmation/undo systems are unchanged.

## License

Adapted Mark-LVII material is attributed in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). The upstream CC BY-NC 4.0 terms continue to apply.
