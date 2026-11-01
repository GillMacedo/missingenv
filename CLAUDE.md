# missingenv

Claude Code skill and CLI that compares the env vars code reads with what deploy files set.

## Architecture
`plugin/scripts/missingenv.py` holds all the logic: `walk` finds files, `scan_code` and the `*_names` readers collect names, and `decide` turns them into findings. `plugin/skills/checking-env-config/SKILL.md` tells Claude how to use it. See `docs/architecture.md`.

## Commands
- `make test`: unit tests and project checks
- `make lint`: manifest validation
- `make demo`: scan `examples/shop`

## Conventions
- Python 3.10+, standard library only. No network calls.
- Never open real `.env` files, and never store or print a value.
- Each code pattern has tests for what it finds and what it must not.

## Do and don't
- Do try a new pattern on a real repo and read what it flags.
- Don't say a variable is definitely missing in production.

## Definition of done
`make test` and `make lint` pass, and `ROADMAP.md` and docs are updated when relevant.
