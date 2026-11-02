# missingenv: find environment variables your deploy doesn't set

[![CI](https://github.com/GillMacedo/missingenv/actions/workflows/ci.yml/badge.svg)](https://github.com/GillMacedo/missingenv/actions/workflows/ci.yml) [![MIT license](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

**A Claude Code skill and read-only CLI that compares the environment variables your code reads with what your Dockerfile, Compose, Kubernetes and `.env.example` files set. It prints names only, and never opens real `.env` files.**

A new `os.Getenv` call passes every test, then the service crashes in production because nobody added the setting to the deploy. `missingenv` finds those gaps across Go, Python, JavaScript, TypeScript, Ruby, Java, Kotlin, Rust and PHP, along with undocumented and stale settings.

## What you can ask Claude

- "What environment variables does this service need before I deploy it?"
- "Is `.env.example` up to date?"
- "Why does this deploy fail on a missing setting?"
- "Which of these settings are no longer used?"

## Install

As a Claude Code plugin:

    claude plugin marketplace add GillMacedo/missingenv
    claude plugin install missingenv@missingenv-marketplace

Or run the script directly. It needs Python 3.10 or newer, with nothing from pip:

    git clone https://github.com/GillMacedo/missingenv
    python3 missingenv/plugin/scripts/missingenv.py ./my-service

## Example

On the made-up service in `examples/shop`:

    $ make demo
    examples/shop: 4 variables read in 1 code files, compared with 1 deploy files and 1 example files

    HIGH   undeclared: SENTRY_DSN
      main.go:10
      The code reads this with no default that the tool can see, and no deploy or example file sets it.

    MEDIUM not-in-deploy: STRIPE_KEY
      main.go:10
      It's in .env.example but no deploy file sets it, and the code has no default that the tool can see. It may be optional, or set outside this repo.

    MEDIUM not-in-example: LOG_LEVEL
      main.go:10
      A deploy file sets it, but the example file doesn't list it, so a new developer won't know about it.

    LOW    unused: OLD_API_TOKEN
      .env.example
      Set here, but no code in this scan reads it. A framework or library may read it, so check before removing it.

    Only names are compared. Real .env files aren't opened, and platforms, secret managers and CI settings aren't visible.

Add `--format markdown` or `--format json`. `--fail-on` sets the severity that exits 1 in CI: `high` by default, or `medium`, `low` or `none`. Use `--ignore NAME` for a variable you've checked. A folder with no supported code also exits 1, so a scan that checked nothing can't pass.

## Findings

| Finding | Severity | Meaning |
|---|---|---|
| `undeclared` | High | The code reads it with no default, and no deploy or example file mentions it |
| `not-in-deploy` | Medium | It's in an example file but no deploy file, and the code has no default |
| `not-in-example` | Medium | A deploy file sets it, but the example file doesn't list it |
| `undeclared-with-default` | Low | The code has a default or checks for it, but no file mentions it |
| `unused` | Low | A file sets it, but no code in the scan reads it |

## Safety

- **Names only:** it compares names and never prints a value.
- **Real `.env` files stay closed:** it reads example files such as `.env.example`, and never opens `.env` or `.env.production`.
- **Read-only and offline:** it makes no network calls and changes nothing.

## Limits

- **Missing here doesn't mean missing in production.** It can't see secret managers, platform settings, Helm values or anything outside the repo. It notes when `envFrom` or `env_file` could load names it can't see.
- **It reads text, not code.** Names built at runtime aren't counted, though it reports how many reads do that. Config libraries and custom helpers other than `env("NAME")` and Go `env:"NAME"` tags are missed, which can make a setting look `unused`.
- **Default detection is a best guess.** It looks at the same line for a default, a fallback or a comparison.
- **YAML is read line by line,** covering `env`, `environment`, Compose `x-*env*` anchors and ConfigMap `data`.
- Tests, `vendor`, `node_modules` and build output are skipped. CI settings don't count as deploy settings.

## FAQ

**How do I find missing environment variables before a deploy?** Run it on the repo, and start with `undeclared`.

**How do I keep `.env.example` up to date?** `not-in-example` and `undeclared` list the names to add, and `unused` lists ones to check for removal.

**Is it safe to run on a repo with secrets?** It never opens real `.env` files and prints only names, but a variable's name can still say something, so treat the output like your code.

**Is it an MCP server?** No. It's a skill with a bundled script, so it needs no server or package install.

## Tested on

Unit tests cover what each pattern finds and what it must not. It also scanned `go-clean-template`, `documenso` and `ardanlabs/service`, and I read the files behind the noisy results. That led to fixes for Compose anchors, `env()` helpers, reads that check for absence, and Vite built-ins. It hasn't been tested in a fresh Claude session. Expect some noise in large monorepos, so check `undeclared` findings against the code.

## Contributing

Contributions are welcome, from people and from people working with AI agents. See [CONTRIBUTING.md](CONTRIBUTING.md). Good first issues are [listed here](https://github.com/GillMacedo/missingenv/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22).

### How pull requests work

1. **Open a PR.** Fork the repo, work on a branch, and keep it to one change. Write a title that says what changes for users, because it becomes the changelog line: `feat:` goes under Added and `fix:` under Fixed.
2. **Automatic check.** Code changes need tests, and `make test` must pass. Changes over 30 lines need a linked open issue (`Closes #<number>`), and a PR can have at most 800 changed lines. If something is missing, a comment tells you what to fix.
3. **Review.** Claude reviews each PR automatically. Code PRs also get a security review and are tested in a sandbox. The review then merges the PR or asks for changes. PRs that change CI, agent settings, npm or Python dependencies, vendored code or build files can't be merged this way, and a comment says so. The same goes for anything the security review doesn't clear.
4. **Release.** A merge that changes what users install becomes a new version within about two hours, with a GitHub Release and, if the project has one, its npm package. Docs and CI changes wait for the next release.

## AI disclosure

This project was largely generated with Claude Code and reviewed by its maintainer.

## About me

I'm Giulliano Macedo, and I build developer tools at GoTech Solutions. Follow along or get in touch:

- GitHub: [GillMacedo](https://github.com/GillMacedo)
- LinkedIn: [giulliano](https://www.linkedin.com/in/giulliano/)
- X: [@giumacedo](https://x.com/giumacedo)

If `missingenv` saved a deploy, a star helps others find it.

---

Built by [Giulliano Macedo](https://github.com/GillMacedo), GoTech Solutions · [LinkedIn](https://www.linkedin.com/in/giulliano/) · [X](https://x.com/giumacedo)
