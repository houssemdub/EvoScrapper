# Agent Directives & Operating Rules

## Primary Workflows
This repository enforces Addy Osmani's `agent-skills` and the `p2p-streaming-engineering` domain skill:
- **p2p-streaming-engineering**: Follow sequential piece buffering, fMP4 transmuxing, audio downmixing (ITU-R BS.775), and subtitle sanitization rules.
- **spec-driven-development**: Lock input/output specifications and constraints before writing code.
- **test-driven-development**: Write unit tests before writing production implementation. Red -> Green -> Refactor.
- **incremental-implementation**: Only modify one isolated component per turn.
- **doubt-driven-development**: Never assume an API, package behavior, or external dependency works. Verify via execution.

## Hard Operating Constraints
1. **No Speculative Coding**: Do not produce full-file overhauls or rewrites without an explicit approved spec.
2. **Deterministic Verification**: Every single change MUST be verified using `pytest` or a direct Python CLI invocation. If a test fails, do not touch secondary files—fix the immediate failure in place.
3. **Token & Quota Economy**: Keep code modifications scoped strictly to diffs. Do not re-emit untouched code or lengthy narrative explanations.
