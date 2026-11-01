# Architecture

    walk --> scan_code (names read, with places) + yaml, Docker and example readers (names set)
    decide --> findings and notes about what it couldn't see
    render_* --> text, Markdown or JSON

- **Real `.env` files** are matched first and skipped before any read.
- **Only names are stored,** so a value can't reach the output.
- **YAML** is read line by line to avoid a dependency, tracking `env`, `environment`, Compose anchors and ConfigMap `data` blocks.

Key choice: a skill with one standard-library script, not an MCP server. See `decisions/`.
