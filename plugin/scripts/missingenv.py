#!/usr/bin/env python3
"""Compare the environment variables code reads with what deploy files set. Prints names, never values."""

import argparse
import json
import os
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

EXIT_OK, EXIT_FINDINGS, EXIT_USAGE = 0, 1, 2
MAX_FILE_BYTES = 2_000_000  # larger files are almost always generated or data
PLACES_SHOWN = 3
SKIP_DIRS = {".git", "node_modules", "vendor", "dist", "build", "target", ".next", "__pycache__", ".venv", "venv", "testdata", "coverage", "third_party"}
TEST_FILE = re.compile(r"(_test\.go$|\.test\.[jt]sx?$|\.spec\.[jt]sx?$|(^|/)test_[^/]+\.py$|_test\.py$|(^|/)(tests?|__tests__|spec|e2e)/)")
NAME = r"([A-Z][A-Z0-9_]{1,})"
# Set by the platform or the shell, so no deploy file needs to set them.
PLATFORM = re.compile(r"^(PATH|HOME|USER|PWD|SHELL|LANG|LC_\w+|TERM|TMPDIR|TEMP|TMP|HOSTNAME|CI|NODE_ENV|DEBUG|GITHUB_\w+|RUNNER_\w+|KUBERNETES_\w+|POD_\w+|XDG_\w+|EDITOR|PAGER|NO_COLOR|FORCE_COLOR|GO\w+|PYTHON\w+|VIRTUAL_ENV|npm_\w+|VERCEL\w*|NEXT_RUNTIME)$")

# Each pattern: (regex, group holding the name). A default is detected separately.
CODE_PATTERNS = {
    ".go": [rf'os\.(?:Getenv|LookupEnv)\(\s*"{NAME}"\s*\)', rf'`[^`]*\benv:"{NAME}(?:,[^"]*)?"[^`]*`'],
    ".py": [rf'os\.environ\[\s*["\']{NAME}["\']\s*\]', rf'os\.environ\.get\(\s*["\']{NAME}["\']', rf'os\.getenv\(\s*["\']{NAME}["\']'],
    ".js": [rf'process\.env\.{NAME}\b', rf'process\.env\[\s*["\']{NAME}["\']\s*\]', rf'import\.meta\.env\.{NAME}\b', rf'\benv\(\s*["\']{NAME}["\']'],
    ".rb": [rf'ENV\[\s*["\']{NAME}["\']\s*\]', rf'ENV\.fetch\(\s*["\']{NAME}["\']'],
    ".java": [rf'System\.getenv\(\s*"{NAME}"\s*\)'],
    ".rs": [rf'env::var(?:_os)?\(\s*"{NAME}"\s*\)'],
    ".php": [rf'getenv\(\s*["\']{NAME}["\']', rf'\$_ENV\[\s*["\']{NAME}["\']\s*\]', rf'\benv\(\s*["\']{NAME}["\']'],
}
for alias in (".ts", ".tsx", ".jsx", ".mjs", ".cjs"):
    CODE_PATTERNS[alias] = CODE_PATTERNS[".js"]
for alias in (".kt",):
    CODE_PATTERNS[alias] = CODE_PATTERNS[".java"]
DYNAMIC = {
    ".go": r'os\.(?:Getenv|LookupEnv)\(\s*[a-zA-Z_]',
    ".py": r'os\.(?:getenv\(\s*[a-zA-Z_]|environ\[\s*[a-zA-Z_]|environ\.get\(\s*[a-zA-Z_])',
    ".js": r'process\.env\[\s*[a-zA-Z_]',
}
COMMENT = {".go": "//", ".py": "#", ".js": "//", ".ts": "//", ".tsx": "//", ".jsx": "//", ".mjs": "//", ".cjs": "//", ".rb": "#", ".java": "//", ".kt": "//", ".rs": "//", ".php": "//"}
# A default on the same line: a second argument, or a fallback operator after the read.
HAS_DEFAULT = re.compile(r'(?:(?:environ\.get|getenv|ENV\.fetch|\benv)\(\s*["\'][A-Z0-9_]+["\']\s*,)|(?:\b[A-Z0-9_]+["\']?\]?\s*(?:\|\||\?\?)\s*\S)|(?:\benv:"[A-Z0-9_]+[^"]*"[^`]*\benvDefault:)|(?:\benv:"[A-Z0-9_]+,[^"]*default=)|(?:\bor\s+["\'\d])|(?:unwrap_or)')
# A read that's compared or branched on already handles the variable being absent.
CHECKED_READ = re.compile(r'===|!==|==|!=|!!|\bif\b|\bunless\b|\s\?\s|^\s*!')
VITE_BUILTINS = {"BASE_URL", "MODE", "DEV", "PROD", "SSR"}
EXAMPLE_FILE = re.compile(r"(^|/)\.env\.(example|sample|template|dist|defaults?)$|(^|/)(env\.example|example\.env|sample\.env)$")
REAL_ENV_FILE = re.compile(r"(^|/)\.env(\.[\w.-]+)?$")
COMPOSE_FILE = re.compile(r"(^|/)(docker-)?compose[\w.-]*\.ya?ml$")
DOCKERFILE = re.compile(r"(^|/)(Dockerfile|[\w.-]+\.Dockerfile|Dockerfile\.[\w.-]+)$")
WORKFLOW_FILE = re.compile(r"(^|/)\.github/workflows/[^/]+\.ya?ml$")
ENV_LINE = re.compile(rf"^\s*(?:export\s+)?{NAME}\s*=")
YAML_NAME_ITEM = re.compile(rf"^\s*-\s*name:\s*[\"']?{NAME}[\"']?\s*$")
YAML_KEY = re.compile(rf"^\s*[\"']?{NAME}[\"']?\s*:")
COMPOSE_LIST_ITEM = re.compile(rf"^\s*-\s*[\"']?{NAME}(?:=|[\"']?\s*$)")
DOCKER_ENV = re.compile(r"^\s*(ENV|ARG)\s+(.+)$", re.IGNORECASE)


@dataclass
class Variable:
    name: str
    used_at: list = field(default_factory=list)
    has_default: bool = False
    required_in_code: bool = False
    deploy: list = field(default_factory=list)
    example: list = field(default_factory=list)
    ci: list = field(default_factory=list)


@dataclass
class Finding:
    severity: str
    kind: str
    name: str
    where: str
    message: str


@dataclass
class Report:
    root: str
    code_files: int = 0
    deploy_files: list = field(default_factory=list)
    example_files: list = field(default_factory=list)
    ci_files: list = field(default_factory=list)
    findings: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    used: int = 0


def walk(root):
    for folder, subfolders, files in os.walk(root):
        subfolders[:] = [name for name in subfolders if name not in SKIP_DIRS and (not name.startswith(".") or name == ".github")]
        for name in sorted(files):
            path = Path(folder, name)
            yield path, path.relative_to(root).as_posix()


def read_text(path, notes, relative):
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            notes.append(f"Skipped {relative}: larger than {MAX_FILE_BYTES // 1_000_000} MB.")
            return None
        return path.read_text(errors="replace")
    except OSError as error:
        notes.append(f"Couldn't read {relative}: {error.strerror}.")
        return None


def scan_code(text, suffix, relative, variables, counters):
    patterns = CODE_PATTERNS[suffix]
    comment = COMMENT.get(suffix)
    dynamic = DYNAMIC.get(".js" if suffix in (".ts", ".tsx", ".jsx", ".mjs", ".cjs") else suffix)
    for number, line in enumerate(text.splitlines(), 1):
        if comment and line.lstrip().startswith(comment):
            continue
        for pattern in patterns:
            for match in re.finditer(pattern, line):
                if match.group(1) in VITE_BUILTINS and "import.meta.env" in match.group(0):
                    continue
                variable = variables.setdefault(match.group(1), Variable(match.group(1)))
                variable.used_at.append(f"{relative}:{number}")
                if HAS_DEFAULT.search(line) or CHECKED_READ.search(line):
                    variable.has_default = True
        if dynamic and re.search(dynamic, line):
            counters["dynamic"].append(f"{relative}:{number}")


def env_file_names(text):
    return {match.group(1) for match in map(ENV_LINE.match, text.splitlines()) if match}


def indent_of(line):
    return len(line) - len(line.lstrip())


def yaml_env_names(text):
    """Read names under `env:`, `environment:` and ConfigMap `data:` blocks, without a YAML parser."""
    names = set()
    is_configmap = bool(re.search(r"(?m)^kind:\s*ConfigMap\s*$", text))
    header_indent = None  # indentation of the current block's header, or None outside a block
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = indent_of(line)
        is_item = stripped.startswith("-")
        # A block ends at a line less indented than its items. YAML lists may sit level with their key.
        if header_indent is not None and (indent < header_indent or (indent == header_indent and not is_item)):
            header_indent = None
        header = re.match(r"^\s*(?:-\s+)?(env|environment|x-[\w-]*env[\w-]*|data)\s*:\s*(?:&\S+\s*)?$", line)
        if header and (header.group(1) != "data" or is_configmap):
            header_indent = indent
            continue
        if header_indent is None:
            continue
        for pattern in (YAML_NAME_ITEM, COMPOSE_LIST_ITEM, YAML_KEY):
            match = pattern.match(line)
            if match:
                names.add(match.group(1))
                break
    return names


def dockerfile_names(text):
    names = set()
    for line in text.splitlines():
        match = DOCKER_ENV.match(line)
        if match:
            names.update(re.findall(rf"(?:^|\s){NAME}(?==|\s|$)", match.group(2).split("#")[0]))
    return names


def uses_outside_sources(text):
    """envFrom and env_file load names this tool can't see."""
    return bool(re.search(r"(?m)^\s*(-\s+)?(envFrom|env_file)\s*:", text))


def looks_like_kubernetes(text):
    return bool(re.search(r"(?m)^apiVersion:", text) and re.search(r"(?m)^kind:", text))


def scan(root):
    report = Report(root=str(root))
    variables = {}
    counters = {"dynamic": [], "outside": []}
    for path, relative in walk(root):
        if EXAMPLE_FILE.search(relative):
            text = read_text(path, report.notes, relative)
            if text is not None:
                report.example_files.append(relative)
                for name in env_file_names(text):
                    variables.setdefault(name, Variable(name)).example.append(relative)
            continue
        if REAL_ENV_FILE.search(relative):
            continue  # real .env files can hold secrets, so they're never opened
        suffix = path.suffix.lower()
        if suffix in CODE_PATTERNS and not TEST_FILE.search(relative):
            text = read_text(path, report.notes, relative)
            if text is not None:
                report.code_files += 1
                scan_code(text, suffix, relative, variables, counters)
            continue
        if DOCKERFILE.search(relative):
            text = read_text(path, report.notes, relative)
            if text is not None:
                report.deploy_files.append(relative)
                for name in dockerfile_names(text):
                    variables.setdefault(name, Variable(name)).deploy.append(relative)
            continue
        if suffix in (".yaml", ".yml"):
            text = read_text(path, report.notes, relative)
            if text is None:
                continue
            if WORKFLOW_FILE.search(relative):
                report.ci_files.append(relative)
                for name in yaml_env_names(text):
                    variables.setdefault(name, Variable(name)).ci.append(relative)
            elif COMPOSE_FILE.search(relative) or looks_like_kubernetes(text):
                report.deploy_files.append(relative)
                for name in yaml_env_names(text):
                    variables.setdefault(name, Variable(name)).deploy.append(relative)
                if uses_outside_sources(text):
                    counters["outside"].append(relative)
    decide(report, variables, counters)
    return report


def decide(report, variables, counters):
    has_deploy = bool(report.deploy_files)
    has_example = bool(report.example_files)
    used = {name: item for name, item in variables.items() if item.used_at}
    report.used = len(used)
    for name, item in sorted(variables.items()):
        if PLATFORM.match(name):
            continue
        place = ", ".join(item.used_at[:PLACES_SHOWN]) + (f" +{len(item.used_at) - PLACES_SHOWN} more" if len(item.used_at) > PLACES_SHOWN else "")
        if item.used_at:
            if not item.deploy and not item.example:
                if item.has_default:
                    report.findings.append(Finding("LOW", "undeclared-with-default", name, place, "The code has a default or checks for it, and no file mentions it, so it's easy to miss that this setting exists."))
                else:
                    report.findings.append(Finding("HIGH", "undeclared", name, place, "The code reads this with no default that the tool can see, and no deploy or example file sets it."))
            elif has_deploy and not item.deploy and not item.has_default:
                report.findings.append(Finding("MEDIUM", "not-in-deploy", name, place, f"It's in {item.example[0]} but no deploy file sets it, and the code has no default that the tool can see. It may be optional, or set outside this repo."))
            elif has_example and not item.example and not item.has_default:
                report.findings.append(Finding("MEDIUM", "not-in-example", name, place, "A deploy file sets it, but the example file doesn't list it, so a new developer won't know about it."))
        elif item.deploy or item.example:
            source = (item.deploy + item.example)[0]
            report.findings.append(Finding("LOW", "unused", name, source, "Set here, but no code in this scan reads it. A framework or library may read it, so check before removing it."))
    order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    report.findings.sort(key=lambda finding: (order[finding.severity], finding.kind, finding.name))
    if not has_deploy:
        report.notes.append("No Dockerfile, Compose or Kubernetes files found. Variables were only compared with example files.")
    if not has_example:
        report.notes.append("No example env file found, such as .env.example.")
    if counters["outside"]:
        report.notes.append(f"{len(counters['outside'])} files use envFrom or env_file, which load names this tool can't see: {', '.join(counters['outside'][:PLACES_SHOWN])}. Names shown as missing may be set there.")
    if counters["dynamic"]:
        report.notes.append(f"{len(counters['dynamic'])} reads use a computed name, so they aren't counted: {', '.join(counters['dynamic'][:PLACES_SHOWN])}.")


def render_text(report):
    lines = [f"{report.root}: {report.used} variables read in {report.code_files} code files, compared with {len(report.deploy_files)} deploy files and {len(report.example_files)} example files"]
    for finding in report.findings:
        lines += ["", f"{finding.severity:<6} {finding.kind}: {finding.name}", f"  {finding.where}", f"  {finding.message}"]
    if report.notes:
        lines += ["", "What this couldn't see:"]
        lines.extend(f"  {note}" for note in report.notes)
    lines += ["", "Only names are compared. Real .env files aren't opened, and platforms, secret managers and CI settings aren't visible."]
    return "\n".join(lines)


def render_markdown(report):
    lines = [f"## missingenv: {len(report.findings)} findings", "", "| Severity | Kind | Variable | Where | Why |", "|---|---|---|---|---|"]
    lines.extend(f"| {f.severity} | {f.kind} | `{f.name}` | `{f.where}` | {f.message} |" for f in report.findings)
    if report.notes:
        lines += ["", "### What this couldn't see", ""]
        lines.extend(f"- {note}" for note in report.notes)
    return "\n".join(lines)


def render_json(report):
    return json.dumps(asdict(report), indent=2)


RENDERERS = {"text": render_text, "markdown": render_markdown, "json": render_json}
SEVERITY = {"high": {"HIGH"}, "medium": {"HIGH", "MEDIUM"}, "low": {"HIGH", "MEDIUM", "LOW"}, "none": set()}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Compare the environment variables code reads with what deploy files set. Prints names, never values.")
    parser.add_argument("path", nargs="?", default=".", help="folder to scan (default: current folder)")
    parser.add_argument("--format", choices=sorted(RENDERERS), default="text")
    parser.add_argument("--fail-on", choices=sorted(SEVERITY), default="high", help="exit 1 at this severity or above (default high)")
    parser.add_argument("--ignore", action="append", default=[], metavar="NAME", help="variable to leave out; repeatable")
    args = parser.parse_args(argv)
    root = Path(args.path)
    if not root.is_dir():
        parser.error(f"{args.path} isn't a folder")
    report = scan(root)
    report.findings = [finding for finding in report.findings if finding.name not in args.ignore]
    print(RENDERERS[args.format](report))
    if report.code_files == 0:
        print("missingenv: no supported code files found, so nothing was checked", file=sys.stderr)
        return EXIT_FINDINGS
    return EXIT_FINDINGS if any(finding.severity in SEVERITY[args.fail_on] for finding in report.findings) else EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
