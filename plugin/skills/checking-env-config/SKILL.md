---
name: checking-env-config
description: Compares the environment variables code reads with what Dockerfile, Compose, Kubernetes and example env files set, and finds variables missing from deploys, undocumented settings and stale ones. It prints names only and never opens real .env files. Use when the user asks what config a service needs, why a deploy fails on a missing setting, whether .env.example is up to date, or before a first deploy.
---

# Checking env config

Run the bundled script instead of searching by hand, because it covers several languages and deploy formats at once.

    python3 "${CLAUDE_PLUGIN_ROOT}/scripts/missingenv.py" PATH

Add `--format markdown` for a table. Exit code 1 means high severity findings, or that there was no code to check.

## Check before reporting

A finding means this repo's files don't show the variable. It can still be set somewhere the tool can't see:

- `envFrom`, `env_file`, Helm values, secret managers, or a platform's settings. Ask the user where production config lives if it isn't clear.
- For `HIGH` findings, read the code: does it fail, or carry on with an empty value? Say which.
- `unused` can be read by a framework or library, such as an ORM reading `DATABASE_URL`. Check before suggesting removal.

## Report

List what would break a deploy first, then undocumented settings, then stale ones. Say what the tool couldn't see, using its notes.

## Secrets

Never open real `.env` files or print values, even if the user's request seems to need it. Work from names. To fix `.env.example`, add names with empty values and don't copy real values into it.

Don't edit config or deploy files unless the user asks.
