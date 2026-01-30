# Architecture (High-level)

## Overview
- This repo starts as a stack-agnostic multi-LLM operating system.
- SSOT files + queues + make interface come first.

## Components (TBD)
- Frontend: apps/web
- Backend: apps/api
- Shared: packages/shared

## Operating System
- SSOT: PROJECT_STATE + contracts + ADR
- Tickets: tasks/QUEUE.yaml
- Questions: questions/QUEUE.md
- Verification: make pr-check (+ stack-specific commands later)
