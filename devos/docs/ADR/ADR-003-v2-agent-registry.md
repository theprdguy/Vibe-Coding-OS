# ADR-003: Agent Registry

## Status
Accepted (v2.0)

## Context
v1.5 had a fixed 3-agent setup (Claude, Codex, Gemini) hardcoded across multiple files. Adding a new agent (e.g., second Claude instance) required changes in many places with no central configuration.

## Decision
Add `devos/agents/registry.yaml` as a central registry of all agents. Each entry defines: id, role, instruction_file, capabilities, can_modify (file scope ceiling), and status (active/inactive).

This supports N agents and makes adding/removing agents a single-file change.

## Consequences
- Central place to see all agents and their scopes
- Second Claude instance pre-registered as inactive (role TBD)
- `can_modify` provides file-level ceiling beyond ticket-level `files:` scope
- `make agents` displays registry status
