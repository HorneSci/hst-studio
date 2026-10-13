"""Regression tests for the shell installer and verifier's offline contracts."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
FAKE_PYTHON = r'''#!/usr/bin/env python3
import json
import os
from pathlib import Path
import shutil
import sys

args = sys.argv[1:]
if args[:2] == ["-m", "venv"]:
    target = Path(args[2])
    bindir = target / "bin"
    bindir.mkdir(parents=True, exist_ok=True)
    executable = bindir / "python"
    shutil.copyfile(__file__, executable)
    executable.chmod(0o755)
    raise SystemExit(0)

if args[:2] == ["-m", "pytest"]:
    if any("hstcore-py/tests" in arg for arg in args):
        print("FAKE binding conformance ran")
        raise SystemExit(int(os.environ.get("FAKE_BINDING_TEST_EXIT", "0")))
    raise SystemExit(0)

if args[:2] == ["-m", "pip"]:
    log = os.environ.get("FAKE_PIP_LOG")
    if log:
        with open(log, "a", encoding="utf-8") as f:
            f.write(json.dumps(args[2:]) + "\n")
    if os.environ.get("FAIL_HSTCORE_INSTALL") == "1" and "./packages/hstcore-py" in args:
        raise SystemExit(23)
    if "pytest" in args and os.environ.get("FAIL_PYTEST_INSTALL") == "1":
        raise SystemExit(24)
    raise SystemExit(0)

if args and args[0] == "-c":
    code = args[1] if len(args) > 1 else ""
    if "import hstcore" in code and os.environ.get("FAKE_BROKEN_HSTCORE") == "1":
        raise SystemExit(1)
    if "import pytest" in code and os.environ.get("FAKE_NO_PYTEST") == "1":
        raise SystemExit(1)
    if "sys.version_info" in code and "print" in code:
        print("3.12")
    raise SystemExit(0)

if args and args[0] == "-":
    sys.stdin.read()
    raise SystemExit(0)

raise SystemExit(0)
'''


def write_executable(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = content.replace("#!/usr/bin/env python3", "#!" + sys.executable)
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def checksum_manifest(root: Path) -> None:
    rows = []
    for name in ("install.sh", "verify.sh"):
        digest = hashlib.sha256((root / name).read_bytes()).hexdigest()
        rows.append(f"{digest}  {name}")
    (root / "SHA256SUMS").write_text("\n".join(rows) + "\n", encoding="utf-8")


@unittest.skipIf(os.name == "nt", "POSIX shell fixtures require executable scripts and symlinks")
class OfflineScriptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="hst-offline-scripts-")
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def fake_python(self, root: Path) -> Path:
        path = root / "fake-python"
        write_executable(path, FAKE_PYTHON)
        return path

    def base_install_tree(self, root: Path) -> None:
        shutil.copy2(ROOT / "install.sh", root / "install.sh")
        for package in ("spdelta", "bindnum", "claimlint", "fitscreen"):
            (root / "packages" / package).mkdir(parents=True)
        (root / "wheelhouse assets").mkdir()

    def test_offline_install_applies_wheelhouse_to_pip_upgrade_and_packages(self) -> None:
        self.base_install_tree(self.root)
        fake = self.fake_python(self.root)
        log = self.root / "pip.jsonl"
        wheels = self.root / "wheelhouse assets"
        env = os.environ.copy()
        env.update({
            "PYTHON": str(fake),
            "HST_VENV": str(self.root / "venv"),
            "FAKE_PIP_LOG": str(log),
        })

        result = subprocess.run(
            ["bash", "install.sh", "--wheels", str(wheels)],
            cwd=self.root,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        calls = [json.loads(line) for line in log.read_text().splitlines()]
        upgrade = next(call for call in calls if "--upgrade" in call)
        self.assertIn("--no-index", upgrade)
        find_links = upgrade.index("--find-links")
        self.assertEqual(upgrade[find_links + 1], str(wheels))
        self.assertTrue(all("--no-index" in call for call in calls))
        self.assertTrue(all("--find-links" in call for call in calls))

    def test_present_runtime_binding_install_failure_is_fatal(self) -> None:
        self.base_install_tree(self.root)
        (self.root / "packages" / "hstcore-py").mkdir()
        fake = self.fake_python(self.root)
        env = os.environ.copy()
        env.update({
            "PYTHON": str(fake),
            "HST_VENV": str(self.root / "venv"),
            "FAIL_HSTCORE_INSTALL": "1",
        })

        result = subprocess.run(
            ["bash", "install.sh", "--wheels", str(self.root / "wheelhouse assets")],
            cwd=self.root,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("INSTALL FAILED", result.stdout + result.stderr)
        self.assertIn("packages/hstcore-py", result.stdout + result.stderr)
        self.assertNotIn("skipped", result.stdout.lower())

    def test_verify_uses_offline_wheelhouse_for_missing_pytest(self) -> None:
        shutil.copy2(ROOT / "verify.sh", self.root / "verify.sh")
        shutil.copy2(ROOT / "install.sh", self.root / "install.sh")
        (self.root / "packages" / "hstcore-dotnet").mkdir(parents=True)
        checksum_manifest(self.root)
        fake = self.fake_python(self.root)
        venv_python = self.root / "venv" / "bin" / "python"
        venv_python.parent.mkdir(parents=True)
        shutil.copyfile(fake, venv_python)
        venv_python.chmod(0o755)
        log = self.root / "pip.jsonl"
        wheels = self.root / "wheelhouse assets"
        wheels.mkdir()
        env = os.environ.copy()
        env.update({
            "HST_VENV": str(self.root / "venv"),
            "FAKE_PIP_LOG": str(log),
            "FAKE_NO_PYTEST": "1",
            "FAIL_PYTEST_INSTALL": "1",
        })

        result = subprocess.run(
            ["bash", "verify.sh", "--wheels", str(wheels)],
            cwd=self.root,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        calls = [json.loads(line) for line in log.read_text().splitlines()]
        pytest = next(call for call in calls if "pytest" in call)
        self.assertIn("--no-index", pytest)
        find_links = pytest.index("--find-links")
        self.assertEqual(pytest[find_links + 1], str(wheels))
        self.assertIn("pytest unavailable offline", result.stdout)
        self.assertIn("no test project is included", result.stdout)

    def test_verifier_stops_before_running_binaries_without_checksum_tool(self) -> None:
        shutil.copy2(ROOT / "verify.sh", self.root / "verify.sh")
        (self.root / "SHA256SUMS").write_text("invalid checksum manifest\n", encoding="utf-8")
        marker = self.root / "binary-ran"
        write_executable(
            self.root / "bin" / "hst-compile.fake",
            "#!/bin/sh\nprintf ran > \"$MARKER\"\n",
        )

        write_executable(self.root / ".venv" / "bin" / "python", FAKE_PYTHON)
        restricted_path = self.root / "restricted-path"
        restricted_path.mkdir()
        for tool in ("dirname", "uname", "tr", "grep", "sed", "head", "tail",
                     "basename", "cat", "mktemp", "rm", "ls", "cut"):
            resolved = shutil.which(tool)
            if resolved:
                (restricted_path / tool).symlink_to(resolved)
        env = os.environ.copy()
        env["PATH"] = str(restricted_path)
        env["MARKER"] = str(marker)
        write_executable(self.root / ".venv" / "bin" / "python", FAKE_PYTHON)

        result = subprocess.run(
            ["/bin/bash", "verify.sh"],
            cwd=self.root,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("cannot verify", result.stdout + result.stderr)
        self.assertFalse(marker.exists(), "verify.sh executed a bundled binary without verifying it")

    def test_verifier_stops_before_running_binaries_on_checksum_mismatch(self) -> None:
        shutil.copy2(ROOT / "verify.sh", self.root / "verify.sh")
        (self.root / "SHA256SUMS").write_text("0" * 64 + "  bin/hst-compile.fake\n", encoding="utf-8")
        marker = self.root / "binary-ran"
        write_executable(
            self.root / "bin" / "hst-compile.fake",
            "#!/bin/sh\nprintf ran > \"$MARKER\"\n",
        )
        env = os.environ.copy()
        env["MARKER"] = str(marker)
        write_executable(self.root / ".venv" / "bin" / "python", FAKE_PYTHON)

        result = subprocess.run(
            ["bash", "verify.sh"],
            cwd=self.root,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("does not match", result.stdout + result.stderr)
        self.assertFalse(marker.exists(), "verify.sh executed a binary after a checksum mismatch")

    def test_empty_wheelhouse_argument_is_rejected(self) -> None:
        env = os.environ.copy()
        env["PYTHON"] = str(self.fake_python(self.root))
        for script in ("install.sh", "verify.sh"):
            shutil.copy2(ROOT / script, self.root / script)
            result = subprocess.run(["bash", script, "--wheels="], cwd=self.root, env=env,
                                    text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("needs a directory", result.stdout + result.stderr)

    def test_binding_suite_failure_is_not_tool_presence_success(self) -> None:
        shutil.copy2(ROOT / "verify.sh", self.root / "verify.sh")
        (self.root / "packages" / "hstcore-py" / "tests").mkdir(parents=True)
        fake = self.fake_python(self.root)
        vpy = self.root / "venv" / "bin" / "python"
        vpy.parent.mkdir(parents=True)
        shutil.copy2(fake, vpy)
        env = os.environ.copy()
        env.update(HST_VENV=str(self.root / "venv"), FAKE_BINDING_TEST_EXIT="17")
        result = subprocess.run(["bash", "verify.sh", "--quick"], cwd=self.root,
                                env=env, text=True, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("FAKE binding conformance ran", result.stdout)
        self.assertIn("hstcore-py conformance", result.stdout)
        self.assertIn("omitted by --quick", result.stdout)

    def test_present_binding_import_failure_is_fatal(self) -> None:
        shutil.copy2(ROOT / "verify.sh", self.root / "verify.sh")
        (self.root / "packages" / "hstcore-py").mkdir(parents=True)
        (self.root / "bin").mkdir()
        fake = self.fake_python(self.root)
        vpy = self.root / "venv" / "bin" / "python"
        vpy.parent.mkdir(parents=True)
        shutil.copy2(fake, vpy)
        env = os.environ.copy()
        env.update(HST_VENV=str(self.root / "venv"), FAKE_BROKEN_HSTCORE="1")
        result = subprocess.run(["bash", "verify.sh", "--quick"], cwd=self.root,
                                env=env, text=True, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("present but does not import", result.stdout)

    def test_verifier_requires_manifest_when_bundled_binary_exists(self) -> None:
        shutil.copy2(ROOT / "verify.sh", self.root / "verify.sh")
        write_executable(self.root / "bin" / "hst-compile.fake", "#!/bin/sh\nexit 0\n")

        result = subprocess.run(
            ["bash", "verify.sh"],
            cwd=self.root,
            env=os.environ.copy(),
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SHA256SUMS", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
