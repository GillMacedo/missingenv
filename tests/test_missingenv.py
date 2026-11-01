import contextlib
import io
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "plugin" / "scripts"))
import missingenv as m  # noqa: E402

K8S = """apiVersion: apps/v1
kind: Deployment
spec:
  template:
    spec:
      containers:
        - name: api
          env:
            - name: IN_DEPLOY
              value: x
          args:
            - NOT_ENV
"""


class Base(unittest.TestCase):
    def scan(self, files):
        with tempfile.TemporaryDirectory() as temp:
            for name, text in files.items():
                path = Path(temp, name)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text)
            return m.scan(Path(temp))

    def kinds(self, files):
        return {finding.name: finding.kind for finding in self.scan(files).findings}


class CodeTest(Base):
    def test_each_language(self):
        cases = {
            "a.go": 'os.Getenv("GO_A1")\nos.LookupEnv("GO_A2")\n',
            "a.py": 'os.environ["PY_A1"]\nos.environ.get("PY_A2")\nos.getenv("PY_A3")\n',
            "a.ts": 'process.env.TS_A1\nprocess.env["TS_A2"]\nimport.meta.env.TS_A3\n',
            "a.rb": 'ENV["RB_A1"]\nENV.fetch("RB_A2")\n',
            "A.java": 'System.getenv("JV_A1")\n',
            "a.rs": 'env::var("RS_A1")\n',
            "a.php": "getenv('PH_A1')\n",
        }
        found = self.kinds(cases)
        for name in ("PY_A1", "PY_A2", "PY_A3", "TS_A1", "TS_A2", "TS_A3", "RB_A1", "RB_A2", "JV_A1", "RS_A1", "PH_A1"):
            self.assertEqual(found.get(name), "undeclared", name)

    def test_checked_reads_count_as_optional(self):
        found = self.kinds({"a.ts": "if (process.env.CHECK_ONE) {}\nconst a = process.env.CHECK_TWO === 'true'\nconst b = process.env.READ_PLAIN\nconst c = process.env.CHECK_THREE ? 1 : 2\n"})
        self.assertEqual(found["READ_PLAIN"], "undeclared")
        for name in ("CHECK_ONE", "CHECK_TWO", "CHECK_THREE"):
            self.assertEqual(found[name], "undeclared-with-default", name)

    def test_vite_builtins(self):
        found = self.kinds({"a.ts": "import.meta.env.BASE_URL\nprocess.env.BASE_URL\n"})
        self.assertEqual(found, {"BASE_URL": "undeclared"})

    def test_env_helper(self):
        found = self.kinds({"a.ts": "env('HELPER_ONE')\nenv('HELPER_TWO', 'x')\nmyenv('NOT_HELPER')\n"})
        self.assertEqual(found, {"HELPER_ONE": "undeclared", "HELPER_TWO": "undeclared-with-default"})

    def test_struct_tags(self):
        found = self.kinds({"a.go": 'type C struct {\n\tA string `env:"TAG_ONE,required"`\n\tB string `env:"TAG_TWO" envDefault:"x"`\n}\n'})
        self.assertEqual(found["TAG_ONE"], "undeclared")
        self.assertEqual(found["TAG_TWO"], "undeclared-with-default")

    def test_defaults(self):
        found = self.kinds({
            "a.py": 'os.environ.get("HAS_D1", "x")\nos.getenv("HAS_D2", "x")\nos.getenv("NO_D1")\nos.getenv("HAS_D3") or "x"\n',
            "a.ts": 'process.env.HAS_D4 || "x"\nprocess.env.HAS_D5 ?? "x"\nprocess.env.NO_D2\n',
            "a.rb": 'ENV.fetch("HAS_D6", "x")\n',
        })
        for name in ("HAS_D1", "HAS_D2", "HAS_D3", "HAS_D4", "HAS_D5", "HAS_D6"):
            self.assertEqual(found[name], "undeclared-with-default", name)
        self.assertEqual(found["NO_D1"], "undeclared")
        self.assertEqual(found["NO_D2"], "undeclared")

    def test_comments_tests_and_vendored_code_are_skipped(self):
        found = self.kinds({
            "a.go": '// os.Getenv("IN_COMMENT")\n',
            "a_test.go": 'os.Getenv("IN_TEST_GO")\n',
            "tests/a.py": 'os.getenv("IN_TEST_PY")\n',
            "vendor/a.go": 'os.Getenv("IN_VENDOR")\n',
            "node_modules/a.js": "process.env.IN_MODULES\n",
        })
        self.assertEqual(found, {})

    def test_platform_variables_are_left_out(self):
        self.assertEqual(self.kinds({"a.go": 'os.Getenv("HOME")\nos.Getenv("GITHUB_SHA")\nos.Getenv("NODE_ENV")\n'}), {})

    def test_computed_names_are_reported(self):
        report = self.scan({"a.go": "os.Getenv(key)\n"})
        self.assertTrue(any("computed name" in note for note in report.notes))


class SourcesTest(Base):
    def test_kubernetes_env(self):
        found = self.kinds({"a.go": 'os.Getenv("IN_DEPLOY")\nos.Getenv("NOT_ENV")\n', "k8s/d.yaml": K8S})
        self.assertNotIn("IN_DEPLOY", found)
        self.assertEqual(found["NOT_ENV"], "undeclared")

    def test_configmap_data(self):
        cm = "apiVersion: v1\nkind: ConfigMap\ndata:\n  FROM_CM: x\nmetadata:\n  labels:\n    NOT_THIS: x\n"
        found = self.kinds({"a.go": 'os.Getenv("FROM_CM")\nos.Getenv("NOT_THIS")\n', "cm.yaml": cm})
        self.assertNotIn("FROM_CM", found)
        self.assertEqual(found["NOT_THIS"], "undeclared")

    def test_compose_map_and_list(self):
        compose = "services:\n  a:\n    environment:\n      MAP_ONE: x\n  b:\n    environment:\n      - LIST_ONE=x\n      - LIST_TWO\n    ports:\n      - PORT_THING\n"
        found = self.kinds({"a.go": 'os.Getenv("MAP_ONE")\nos.Getenv("LIST_ONE")\nos.Getenv("LIST_TWO")\nos.Getenv("PORT_THING")\n', "docker-compose.yml": compose})
        self.assertEqual(found, {"PORT_THING": "undeclared"})

    def test_compose_anchor_block(self):
        compose = "x-app-environment: &app-env\n  FROM_ANCHOR: x\nservices:\n  a:\n    environment:\n      <<: *app-env\n"
        self.assertEqual(self.kinds({"a.go": 'os.Getenv("FROM_ANCHOR")\n', "docker-compose.yml": compose}), {})

    def test_list_level_with_its_key(self):
        compose = "services:\n  a:\n    environment:\n    - LEVEL_ONE=x\n    ports:\n    - NOT_ENV_TWO\n"
        found = self.kinds({"a.go": 'os.Getenv("LEVEL_ONE")\nos.Getenv("NOT_ENV_TWO")\n', "compose.yaml": compose})
        self.assertEqual(found, {"NOT_ENV_TWO": "undeclared"})

    def test_dockerfile(self):
        docker = "FROM x\nENV FROM_ENV=1 ALSO_ENV=2\nENV OLD_STYLE value\nARG FROM_ARG\n"
        found = self.kinds({"a.go": 'os.Getenv("FROM_ENV")\nos.Getenv("ALSO_ENV")\nos.Getenv("OLD_STYLE")\nos.Getenv("FROM_ARG")\n', "Dockerfile": docker})
        self.assertEqual(found, {})

    def test_outside_sources_are_noted(self):
        report = self.scan({"a.go": 'os.Getenv("X_Y")\n', "d.yaml": K8S.replace("env:", "envFrom:")})
        self.assertTrue(any("envFrom or env_file" in note for note in report.notes))

    def test_real_env_files_are_never_opened(self):
        secret = "from-real-file"
        report = self.scan({"a.go": 'os.Getenv("FROM_REAL")\n', ".env": f"FROM_REAL={secret}\n", ".env.production": f"FROM_REAL={secret}\n"})
        self.assertEqual([finding.kind for finding in report.findings], ["undeclared"])
        self.assertNotIn(secret, m.render_json(report))

    def test_values_are_never_printed(self):
        value = "value-that-must-not-print"
        files = {"a.go": 'os.Getenv("SOME_KEY")\n', ".env.example": f"SOME_KEY={value}\nOTHER_KEY={value}\n", "Dockerfile": f"ENV THIRD_KEY={value}\n"}
        report = self.scan(files)
        for render in m.RENDERERS.values():
            self.assertNotIn(value, render(report))

    def test_ci_settings_dont_count_as_deploy(self):
        flow = "on: push\njobs:\n  a:\n    env:\n      ONLY_CI: x\n"
        self.assertEqual(self.kinds({"a.go": 'os.Getenv("ONLY_CI")\n', ".github/workflows/a.yml": flow})["ONLY_CI"], "undeclared")


class KindsTest(Base):
    def test_in_example_not_in_deploy(self):
        found = self.kinds({"a.go": 'os.Getenv("NEEDS_DEPLOY")\n', ".env.example": "NEEDS_DEPLOY=\n", "k.yaml": K8S})
        self.assertEqual(found["NEEDS_DEPLOY"], "not-in-deploy")

    def test_in_deploy_not_in_example(self):
        found = self.kinds({"a.go": 'os.Getenv("IN_DEPLOY")\n', ".env.example": "OTHER_ONE=\n", "k.yaml": K8S})
        self.assertEqual(found["IN_DEPLOY"], "not-in-example")

    def test_example_only_repo_isnt_told_about_deploy(self):
        report = self.scan({"a.go": 'os.Getenv("ONLY_EX")\n', ".env.example": "ONLY_EX=\n"})
        self.assertEqual(report.findings, [])
        self.assertTrue(any("No Dockerfile" in note for note in report.notes))

    def test_unused(self):
        self.assertEqual(self.kinds({"a.go": "package a\n", ".env.example": "OLD_ONE=\n"})["OLD_ONE"], "unused")


class CliTest(unittest.TestCase):
    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = m.main(list(args))
        return code, out.getvalue(), err.getvalue()

    def test_example(self):
        code, out, _ = self.run_cli("--format", "json", str(ROOT / "examples" / "shop"))
        self.assertEqual(code, m.EXIT_FINDINGS)
        found = {f["name"]: f["kind"] for f in json.loads(out)["findings"]}
        self.assertEqual(found, {"SENTRY_DSN": "undeclared", "STRIPE_KEY": "not-in-deploy", "LOG_LEVEL": "not-in-example", "OLD_API_TOKEN": "unused"})

    def test_fail_on_and_ignore(self):
        path = str(ROOT / "examples" / "shop")
        self.assertEqual(self.run_cli("--fail-on", "none", path)[0], m.EXIT_OK)
        code, _, _ = self.run_cli("--ignore", "SENTRY_DSN", "--ignore", "STRIPE_KEY", path)
        self.assertEqual(code, m.EXIT_OK)

    def test_nothing_to_check_isnt_a_pass(self):
        with tempfile.TemporaryDirectory() as temp:
            code, _, err = self.run_cli(temp)
        self.assertEqual(code, m.EXIT_FINDINGS)
        self.assertIn("nothing was checked", err)

    def test_bad_path(self):
        with self.assertRaises(SystemExit) as caught, contextlib.redirect_stderr(io.StringIO()):
            m.main(["/no/such/place"])
        self.assertEqual(caught.exception.code, m.EXIT_USAGE)

    def test_markdown(self):
        _, out, _ = self.run_cli("--format", "markdown", str(ROOT / "examples" / "shop"))
        self.assertIn("| HIGH | undeclared | `SENTRY_DSN` |", out)


class ProjectTest(unittest.TestCase):
    def test_standard_library_and_no_network(self):
        source = (ROOT / "plugin" / "scripts" / "missingenv.py").read_text()
        imported = set(re.findall(r"^(?:from|import) (\w+)", source, re.M))
        self.assertLessEqual(imported, {"argparse", "json", "os", "re", "sys", "dataclasses", "pathlib"})

    def test_skill_frontmatter(self):
        text = (ROOT / "plugin" / "skills" / "checking-env-config" / "SKILL.md").read_text()
        self.assertRegex(re.search(r"^name: (.+)$", text, re.M).group(1), r"^[a-z0-9-]{1,64}$")
        self.assertLessEqual(len(re.search(r"^description: (.+)$", text, re.M).group(1)), 1024)

    def test_evals_are_valid(self):
        self.assertGreaterEqual(len(json.loads((ROOT / "evals" / "evals.json").read_text())), 3)


if __name__ == "__main__":
    unittest.main()
