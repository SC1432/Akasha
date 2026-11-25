# ADR-0001: Build as a Claude Code plugin

**Date:** 2026-11-25
**Status:** accepted

## Context

A personal assistant implies some work happens without me in a session (morning brief, weekly digest, processing captures from my phone). Claude Code plugins only run inside an interactive session on my machine.

## Decision

Build Brain as a Claude Code plugin. Unattended work runs as scheduled headless `claude -p` jobs (launchd on macOS).

## Alternatives considered

- **Standalone app on the Claude Agent SDK**, hosted on a server with Telegram as the interface. Always on and phone-first, but requires building a small service (hosting, auth, state) and loses Claude Code's interactive editing.

## Consequences

- Fastest path to something used daily; reuses Claude Code's skills, agents and hooks.
- Scheduled jobs depend on the Mac being awake until an always-on host is chosen (Phase 7).
- The vault, schema and `brainctl` are independent of the agent runtime, so moving to the Agent SDK later does not lose data or tooling.
