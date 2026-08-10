from __future__ import annotations

import json
import importlib.util
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = REPO_ROOT / "skills" / "reverse-engineer-ai-video-tutorial"
sys.path.insert(0, str(SKILL_ROOT / "scripts" / "_runtime"))
from tutorial_re import doctor as runtime_doctor  # noqa: E402
from tutorial_re import cli as runtime_cli  # noqa: E402
from tutorial_re import tools as runtime_tools  # noqa: E402
from tutorial_re.manifest import read_json, write_json  # noqa: E402
from tutorial_re.run_store import create_run, register_artifact, verify_artifacts  # noqa: E402
from tutorial_re.validate import validate_scene_catalog, validate_stage  # noqa: E402

ROOT = SKILL_ROOT
PYTHON = sys.executable
_installer_spec = importlib.util.spec_from_file_location("public_install_skill", ROOT / "scripts" / "install_skill.py")
assert _installer_spec and _installer_spec.loader
installer_module = importlib.util.module_from_spec(_installer_spec)
_installer_spec.loader.exec_module(installer_module)
_prepare_spec = importlib.util.spec_from_file_location("public_prepare_remotion", ROOT / "scripts" / "prepare_remotion.py")
assert _prepare_spec and _prepare_spec.loader
prepare_module = importlib.util.module_from_spec(_prepare_spec)
_prepare_spec.loader.exec_module(prepare_module)
_hyperframes_spec = importlib.util.spec_from_file_location("public_prepare_hyperframes", ROOT / "scripts" / "prepare_hyperframes.py")
assert _hyperframes_spec and _hyperframes_spec.loader
hyperframes_module = importlib.util.module_from_spec(_hyperframes_spec)
_hyperframes_spec.loader.exec_module(hyperframes_module)
_bootstrap_spec = importlib.util.spec_from_file_location("public_bootstrap_runtime", ROOT / "scripts" / "bootstrap_runtime.py")
assert _bootstrap_spec and _bootstrap_spec.loader
bootstrap_module = importlib.util.module_from_spec(_bootstrap_spec)
_bootstrap_spec.loader.exec_module(bootstrap_module)
_run_spec = importlib.util.spec_from_file_location("public_run", ROOT / "scripts" / "run.py")
assert _run_spec and _run_spec.loader
run_module = importlib.util.module_from_spec(_run_spec)
_run_spec.loader.exec_module(run_module)


class PublicPackageSmoke(unittest.TestCase):
    def run_json(self, *args: str, python: str = PYTHON, env: dict[str, str] | None = None) -> dict:
        completed = subprocess.run(
            [python, *args],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)
        return json.loads(completed.stdout)

    def test_frontmatter_and_release_version(self) -> None:
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertTrue(skill.startswith("---\nname: reverse-engineer-ai-video-tutorial\n"))
        release = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        self.assertEqual(release, "0.0.1")
        self.assertEqual(runtime_doctor.__version__, release)
        self.assertEqual(run_module.EXPECTED_RUNTIME_VERSION, release)
        self.assertIn("tutorial-re ==0.0.1", skill)
        self.assertNotIn("tutorial-re >=3,<4", skill)

    def test_malformed_catalog_ids_return_path_error(self) -> None:
        errors = validate_scene_catalog({
            "schema_version": 13,
            "sections": [{"scenes": [{"target_reference_asset_ids": [["nested"]]}]}],
        })
        self.assertTrue(any(
            "sections[0].scenes[0].target_reference_asset_ids[0] must be string" in error
            for error in errors
        ))

    def test_validate_expected_failure_is_structured_json(self) -> None:
        with tempfile.TemporaryDirectory(prefix="tutorial-re-invalid-") as directory:
            completed = subprocess.run(
                [
                    PYTHON,
                    str(ROOT / "scripts" / "run.py"),
                    "validate",
                    "--json",
                    "--run",
                    str(Path(directory) / "missing-run"),
                    "--stage",
                    "guide-complete",
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )
        self.assertEqual(completed.returncode, 2, completed.stderr)
        self.assertNotIn("Traceback", completed.stdout + completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error_code"], "VALIDATION_FAILED")

    def test_validate_malformed_manifest_boundaries_never_crash(self) -> None:
        with tempfile.TemporaryDirectory(prefix="tutorial-re-malformed-") as directory:
            root = Path(directory)
            run = create_run(root, "source", target="tutorial", action="guide")
            manifest = read_json(run.run_dir / "run.json")
            manifest["artifacts"] = [["nested"]]
            write_json(run.run_dir / "run.json", manifest)
            result = validate_stage(run.run_dir, "scaffold")
            self.assertIn("RUN_ARTIFACTS_INVALID", {item["code"] for item in result["errors"]})

            manifest["artifacts"] = []
            write_json(run.run_dir / "run.json", manifest)
            write_json(run.run_dir / "evidence_manifest.json", [])
            result = validate_stage(run.run_dir, "scaffold")
            self.assertIn("EVIDENCE_INVALID", {item["code"] for item in result["errors"]})

            write_json(run.run_dir / "evidence_manifest.json", {"schema_version": 1, "coverage": [], "status": "scaffold"})
            write_json(run.run_dir / "section_map.json", [])
            result = validate_stage(run.run_dir, "section-mapped")
            self.assertIn("SECTION_MAP_INVALID", {item["code"] for item in result["errors"]})

            write_json(run.run_dir / "detail_discovery.json", [])
            result = validate_stage(run.run_dir, "scaffold")
            self.assertIn("DETAIL_DISCOVERY_INVALID", {item["code"] for item in result["errors"]})

    def test_artifact_repair_command_quotes_spaced_run_path(self) -> None:
        with tempfile.TemporaryDirectory(prefix="tutorial re repair ") as directory:
            run = create_run(Path(directory), "source", target="tutorial", action="guide")
            artifact = run.run_dir / "scene catalog.json"
            write_json(artifact, {"schema_version": 13})
            register_artifact(run.run_dir, artifact, role="scene catalog")
            artifact.write_text("{}\n", encoding="utf-8")
            errors = verify_artifacts(run.run_dir)
        self.assertEqual(len(errors), 1)
        self.assertIn(f'--run "{run.run_dir.resolve()}"', errors[0])
        self.assertIn('--path "scene catalog.json"', errors[0])
        self.assertIn('--role "scene catalog"', errors[0])

    def test_local_file_ingest_creates_guide_scaffold_without_network(self) -> None:
        with tempfile.TemporaryDirectory(prefix="tutorial-re-local-ingest-") as directory:
            root = Path(directory)
            video = root / "source.mp4"
            video.write_bytes(b"synthetic-local-video")
            workspace = root / "workspace"
            args = runtime_cli.build_parser().parse_args([
                "ingest", "--video-file", str(video), "--target", "whole tutorial",
                "--workspace-root", str(workspace), "--cache-root", str(workspace / "cache"),
                "--source-cache-root", str(root / "source-cache"), "--skip-transcript",
                "--stop-after", "guide", "--json",
            ])
            output = io.StringIO()
            with mock.patch("sys.stdout", output):
                self.assertEqual(runtime_cli._run_ingest_command(args), 0)
            payload = json.loads(output.getvalue())
            run_dir = Path(payload["run_dir"])
            self.assertTrue((run_dir / "guide.md").is_file())
            self.assertEqual(read_json(run_dir / "scene_catalog.json")["schema_version"], 13)

    def test_repo_root_and_canonical_subtree_select_identical_payload(self) -> None:
        repo_report = self.run_json(
            str(ROOT / "scripts" / "install_skill.py"), "--source", str(REPO_ROOT), "--dry-run", "--json"
        )
        subtree_report = self.run_json(
            str(ROOT / "scripts" / "install_skill.py"), "--source", str(ROOT), "--dry-run", "--json"
        )
        self.assertEqual(repo_report["payload_sha256"], subtree_report["payload_sha256"])
        self.assertEqual(repo_report["files"], subtree_report["files"])

    def test_doctor_runs_without_site_packages(self) -> None:
        report = self.run_json(
            "-S",
            str(ROOT / "scripts" / "run.py"),
            "doctor",
            "--profile",
            "base",
            "--allow-missing",
            "--json",
        )
        self.assertEqual(report["schema_version"], 3)
        self.assertIn("profiles", report)
        self.assertIn(report["state"], {"needs_context", "ready_with_warnings", "ready"})
        self.assertNotIn("Pillow", report["profiles"]["base"]["missing"])

    def test_doctor_exposes_hyperframes_capability_scope(self) -> None:
        report = runtime_doctor.doctor_report("hyperframes")
        self.assertIn("hyperframes", report["profiles"])
        self.assertIn("hyperframes", report["profiles"]["hyperframes"]["required"])
        self.assertIn("hyperframes", report["capabilities"])

    def test_installer_dry_run_allowlist(self) -> None:
        with tempfile.TemporaryDirectory(prefix="tutorial-re-smoke-") as directory:
            target_root = Path(directory) / "skills"
            report = self.run_json(
                str(ROOT / "scripts" / "install_skill.py"),
                "--source",
                str(REPO_ROOT),
                "--skills-root",
                str(target_root),
                "--target",
                str(target_root / "reverse-engineer-ai-video-tutorial"),
                "--dry-run",
                "--json",
            )
        self.assertGreater(report["payload_files"], 0)
        paths = [item["path"] for item in report["files"]]
        self.assertFalse(any("__pycache__" in path or path.endswith(".pyc") for path in paths))
        self.assertNotIn("README.md", paths)
        self.assertNotIn("CHANGELOG.md", paths)
        self.assertNotIn("CONTRIBUTING.md", paths)
        self.assertNotIn("AGENTS.md", paths)
        self.assertIn("requirements.lock", paths)

    def test_agent_install_contract_and_readme_are_first_use_ready(self) -> None:
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        agents = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")
        self.assertLess(readme.index("## Install with an agent — recommended"), readme.index("## Install manually — fallback"))
        self.assertLess(readme.index("## Install manually — fallback"), readme.index("## Capabilities"))
        self.assertIn("Install this skill for Codex:", readme)
        self.assertIn("Install this skill for Cursor:", readme)
        self.assertIn("installs in universal `~/.agents/skills`", readme)
        self.assertIn("Other Agent Skills-compatible hosts, including Claude Code and Gemini CLI", readme)
        self.assertIn("For install-only requests, run `base` doctor", agents)
        self.assertIn("skills/reverse-engineer-ai-video-tutorial/VERSION", agents)
        self.assertIn("Gemini CLI: use `--host shared`", agents)
        self.assertIn("Map generation actions to host-native tools", agents)
        self.assertIn("AGENTS.md", readme)
        self.assertLess(len(agents.splitlines()), 200)
        self.assertLess((REPO_ROOT / "AGENTS.md").stat().st_size, 32 * 1024)
        for phrase in ("--host shared", "--host codex|cursor", "No Python", "Stop conditions", "Final report"):
            self.assertIn(phrase, agents)
        for relative in (
            "skills/reverse-engineer-ai-video-tutorial/scripts/install_skill.py",
            "skills/reverse-engineer-ai-video-tutorial/scripts/install_global.ps1",
            "skills/reverse-engineer-ai-video-tutorial/scripts/install_skill.sh",
        ):
            self.assertTrue((REPO_ROOT / relative).is_file(), relative)
        changelog = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        unreleased = changelog.split("## [Unreleased]", 1)[1].split("## [0.0.1]", 1)[0].strip()
        self.assertEqual(unreleased, "")

    def test_implicit_installer_target_is_universal_shared_root(self) -> None:
        with tempfile.TemporaryDirectory(prefix="tutorial-re-shared-default-") as directory:
            home = Path(directory) / "home"
            home.mkdir()
            output = io.StringIO()
            with mock.patch.object(installer_module.Path, "home", return_value=home), redirect_stdout(output):
                code = installer_module.main(["--source", str(ROOT), "--dry-run", "--json"])
        self.assertEqual(code, 0, output.getvalue())
        report = json.loads(output.getvalue())
        self.assertEqual(report["host"], "shared")
        self.assertEqual(Path(report["skills_root"]), (home / ".agents" / "skills").resolve())

    def test_host_selector_installs_isolated_codex_cursor_shared_targets(self) -> None:
        with tempfile.TemporaryDirectory(prefix="tutorial-re-hosts-") as directory:
            home = Path(directory) / "home"
            home.mkdir()
            roots = {
                "codex": home / ".codex" / "skills",
                "cursor": home / ".cursor" / "skills",
                "shared": home / ".agents" / "skills",
            }
            for host, skills_root in roots.items():
                output = io.StringIO()
                with mock.patch.object(installer_module.Path, "home", return_value=home), redirect_stdout(output):
                    code = installer_module.main(["--source", str(ROOT), "--host", host, "--json"])
                self.assertEqual(code, 0, output.getvalue())
                report = json.loads(output.getvalue())
                target = skills_root / "reverse-engineer-ai-video-tutorial"
                self.assertEqual(report["host"], host)
                self.assertEqual(Path(report["skills_root"]), skills_root.resolve())
                self.assertEqual(Path(report["target"]), target.resolve())
                self.assertEqual(report["approvals_required"], [])
                self.assertIn("system_packages", report["dependency_plan"])
                receipt = json.loads((target / ".install-receipt.json").read_text(encoding="utf-8"))
                self.assertEqual(receipt["host"], host)
                if host == "codex":
                    dry_run = io.StringIO()
                    with mock.patch.object(installer_module.Path, "home", return_value=home), redirect_stdout(dry_run):
                        code = installer_module.main(["--source", str(ROOT), "--host", host, "--dry-run", "--json"])
                    self.assertEqual(code, 0, dry_run.getvalue())
                    dry_report = json.loads(dry_run.getvalue())
                    self.assertEqual(dry_report["approvals_required"], ["replace_existing_install"])
                    self.assertIn("request approval before --force", dry_report["plan"])
                    refused = io.StringIO()
                    with mock.patch.object(installer_module.Path, "home", return_value=home), redirect_stdout(refused):
                        code = installer_module.main(["--source", str(ROOT), "--host", host, "--json"])
                    self.assertEqual(code, 2)
                    self.assertEqual(json.loads(refused.getvalue())["error_code"], "TARGET_EXISTS")
                    updated = io.StringIO()
                    with mock.patch.object(installer_module.Path, "home", return_value=home), redirect_stdout(updated):
                        code = installer_module.main(["--source", str(ROOT), "--host", host, "--force", "--json"])
                    self.assertEqual(code, 0, updated.getvalue())
                    rolled_back = io.StringIO()
                    with mock.patch.object(installer_module.Path, "home", return_value=home), redirect_stdout(rolled_back):
                        code = installer_module.main(["--host", host, "--rollback", "--json"])
                    self.assertEqual(code, 0, rolled_back.getvalue())
                    self.assertEqual(json.loads(rolled_back.getvalue())["action"], "rollback")

    def test_host_selector_rejects_conflicting_root_and_target(self) -> None:
        with tempfile.TemporaryDirectory(prefix="tutorial-re-host-conflict-") as directory:
            home = Path(directory) / "home"
            home.mkdir()
            output = io.StringIO()
            with mock.patch.object(installer_module.Path, "home", return_value=home), redirect_stdout(output):
                code = installer_module.main([
                    "--source", str(ROOT), "--host", "codex",
                    "--skills-root", str(Path(directory) / "custom-skills"), "--json",
                ])
            self.assertEqual(code, 2)
            report = json.loads(output.getvalue())
            self.assertFalse(report["ok"])
            self.assertIn("conflicts with --host codex", report["error"])
            output = io.StringIO()
            with mock.patch.object(installer_module.Path, "home", return_value=home), redirect_stdout(output):
                code = installer_module.main([
                    "--source", str(ROOT), "--host", "codex",
                    "--target", str(Path(directory) / "outside" / "reverse-engineer-ai-video-tutorial"), "--json",
                ])
            self.assertEqual(code, 2)
            self.assertIn("--target conflicts with --host codex", json.loads(output.getvalue())["error"])

    def test_powershell_wrapper_help_and_force_are_safe(self) -> None:
        shell = shutil.which("pwsh") or shutil.which("powershell")
        if not shell:
            self.skipTest("PowerShell unavailable")
        wrapper = ROOT / "scripts" / "install_global.ps1"
        source = wrapper.read_text(encoding="utf-8")
        self.assertIn('[string]$InstallHost = "shared"', source)
        self.assertNotIn('"--host", $InstallHost, "--force"', source)

        help_result = subprocess.run(
            [shell, "-NoProfile", "-File", str(wrapper), "-Help"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        self.assertEqual(help_result.returncode, 0, help_result.stderr)
        self.assertIn("Default target: ~/.agents/skills", help_result.stdout)

        with tempfile.TemporaryDirectory(prefix="tutorial-re-wrapper-") as directory:
            codex_home = Path(directory) / "custom-home"
            base = [shell, "-NoProfile", "-File", str(wrapper), "-CodexHome", str(codex_home), "-Json"]
            first = subprocess.run(base, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=False)
            self.assertEqual(first.returncode, 0, first.stderr or first.stdout)
            second = subprocess.run(base, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=False)
            self.assertEqual(second.returncode, 2, second.stderr or second.stdout)
            self.assertEqual(json.loads(second.stdout)["error_code"], "TARGET_EXISTS")
            third = subprocess.run([*base, "-Force"], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=False)
            self.assertEqual(third.returncode, 0, third.stderr or third.stdout)

    def test_canonical_stock_copy_boundary_excludes_repo_files(self) -> None:
        with tempfile.TemporaryDirectory(prefix="tutorial-re-stock-boundary-") as directory:
            target = Path(directory) / "reverse-engineer-ai-video-tutorial"
            shutil.copytree(ROOT, target)
            self.assertTrue((target / "SKILL.md").is_file())
            for repo_only in ("README.md", "CHANGELOG.md", "CONTRIBUTING.md", ".github", "tests"):
                self.assertFalse((target / repo_only).exists(), repo_only)

    def test_nonempty_unowned_remotion_target_is_rejected(self) -> None:
        target = Path(tempfile.mkdtemp(prefix="tutorial-re-unowned-remotion-"))
        self.addCleanup(lambda: shutil.rmtree(target, ignore_errors=True))
        (target / "authored.tsx").write_text("export const authored = true;\n", encoding="utf-8")
        with self.assertRaises(RuntimeError) as context:
            prepare_module._scaffold_project(target, target.parent / "toolchain", prepare_module.SHARED_PACKAGE)
        self.assertIn("nonempty and not an owned Remotion project", str(context.exception))

    def test_hyperframes_missing_cli_is_approval_gated(self) -> None:
        with tempfile.TemporaryDirectory(prefix="tutorial-re-hyperframes-missing-") as directory:
            workspace = Path(directory)
            missing = runtime_tools.ToolResolution("hyperframes", None, None, "missing", verified=False, error="not found")
            with mock.patch.object(hyperframes_module, "probe_tool", return_value=missing):
                result = hyperframes_module.main(["--repo-root", str(workspace), "--source-id", "source", "--json"])
            self.assertEqual(result, 2)
            self.assertFalse((workspace / "videos" / "source" / "hyperframes").exists())

    def test_hyperframes_discovery_never_uses_npx_without_approval(self) -> None:
        with tempfile.TemporaryDirectory(prefix="tutorial-re-npx-probe-") as directory:
            fake_npx = Path(directory) / ("npx.cmd" if os.name == "nt" else "npx")
            fake_npx.write_text("", encoding="utf-8")

            def which(name: str) -> str | None:
                return str(fake_npx) if name == "npx" else None

            with mock.patch.object(runtime_tools.shutil, "which", side_effect=which):
                plain = runtime_tools.resolve_tool("hyperframes")
                approved = runtime_tools.resolve_tool("hyperframes", allow_network=True)
            self.assertIsNone(plain.command)
            self.assertEqual(plain.source, "missing")
            self.assertEqual(approved.command, (str(fake_npx), "hyperframes"))

    def test_hyperframes_doctor_rejects_old_node_and_missing_ffmpeg(self) -> None:
        cli = {"available": True, "command": ["hyperframes"], "version": "0.7.56"}
        node = {"available": True, "command": ["node"], "version": "v21.9.0"}
        ffmpeg = {"available": False, "command": None, "version": None}
        ffprobe = {"available": True, "command": ["ffprobe"], "version": "6.1.0"}
        report = runtime_doctor._hyperframes_report(cli, node, ffmpeg, ffprobe)
        self.assertFalse(report["ready"])
        self.assertEqual(report["state"], "broken")
        self.assertFalse(report["requirements"]["node"]["ready"])
        self.assertFalse(report["requirements"]["ffmpeg"]["ready"])

    def test_hyperframes_doctor_ignores_optional_update_warning_when_core_is_healthy(self) -> None:
        payload = {"ok": False, "checks": [
            {"name": "Node.js", "ok": True},
            {"name": "FFmpeg", "ok": True},
            {"name": "FFprobe", "ok": True},
            {"name": "Version", "ok": False},
        ]}
        completed = mock.Mock(returncode=0, stdout=json.dumps(payload), stderr="")
        with mock.patch.object(runtime_doctor.subprocess, "run", return_value=completed):
            health = runtime_doctor._hyperframes_cli_health(["hyperframes"])
        self.assertTrue(health["ready"])

    def test_hyperframes_nonempty_unowned_target_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="tutorial-re-hyperframes-owned-") as directory:
            workspace = Path(directory)
            target = workspace / "videos" / "source" / "hyperframes"
            target.mkdir(parents=True)
            (target / "index.html").write_text("authored", encoding="utf-8")
            available = runtime_tools.ToolResolution("hyperframes", ("hyperframes",), "hyperframes", "test", "0.7.56", True)
            with mock.patch.object(hyperframes_module, "probe_tool", return_value=available):
                with self.assertRaises(SystemExit) as context:
                    hyperframes_module.main(["--repo-root", str(workspace), "--source-id", "source"])
            self.assertIn("nonempty and not an owned project", str(context.exception))

    def test_hyperframes_init_failure_leaves_retryable_absent_target(self) -> None:
        with tempfile.TemporaryDirectory(prefix="tutorial-re-hyperframes-init-failure-") as directory:
            workspace = Path(directory)
            available = runtime_tools.ToolResolution("hyperframes", ("hyperframes",), "hyperframes", "test", "0.7.56", True)
            with mock.patch.object(hyperframes_module, "probe_tool", return_value=available), mock.patch.object(
                hyperframes_module, "_run", side_effect=RuntimeError("injected init failure")
            ):
                with self.assertRaises(RuntimeError):
                    hyperframes_module.main(["--repo-root", str(workspace), "--source-id", "source"])
            target = workspace / "videos" / "source" / "hyperframes"
            self.assertFalse(target.exists())
            self.assertFalse(list(target.parent.glob(".hyperframes.stage-*")))
            self.assertFalse(list(target.parent.glob(".hyperframes.init-*.log")))

    def test_hyperframes_existing_project_resume_preserves_authored_files(self) -> None:
        with tempfile.TemporaryDirectory(prefix="tutorial-re-hyperframes-resume-") as directory:
            workspace = Path(directory)
            target = workspace / "videos" / "source" / "hyperframes"
            target.mkdir(parents=True)
            marker = {"name": "authored", "version": 1}
            (target / "hyperframes.json").write_text(json.dumps(marker), encoding="utf-8")
            (target / "index.html").write_text("authored", encoding="utf-8")
            available = runtime_tools.ToolResolution("hyperframes", ("hyperframes",), "hyperframes", "test", "0.7.56", True)

            def fake_run(command: list[str], cwd: Path, log_path: Path, *, timeout_seconds: int) -> None:
                log_path.write_text("native check passed\n", encoding="utf-8")

            with mock.patch.object(hyperframes_module, "probe_tool", return_value=available), mock.patch.object(
                hyperframes_module, "_run", side_effect=fake_run
            ):
                result = hyperframes_module.main(["--repo-root", str(workspace), "--source-id", "source", "--json"])
            self.assertEqual(result, 0)
            self.assertEqual(json.loads((target / "hyperframes.json").read_text(encoding="utf-8")), marker)
            self.assertTrue((target / ".tutorial-re-hyperframes-readiness.json").is_file())

    def test_bootstrap_plan_is_network_free(self) -> None:
        with tempfile.TemporaryDirectory(prefix="tutorial-re-runtime-") as directory:
            env = os.environ.copy()
            env["TUTORIAL_RE_DATA_ROOT"] = directory
            report = self.run_json(
                str(ROOT / "scripts" / "bootstrap_runtime.py"),
                "--plan",
                "--json",
                env=env,
            )
        self.assertFalse(report["ready"])
        self.assertTrue(report["plan"])
        self.assertTrue(report["lock_sha256"])

    def test_bootstrap_rejects_stale_receipt(self) -> None:
        with tempfile.TemporaryDirectory(prefix="tutorial-re-stale-runtime-") as directory:
            data_root = Path(directory)
            metadata = data_root / "runtime" / "runtime.json"
            metadata.parent.mkdir(parents=True)
            metadata.write_text(json.dumps({"schema_version": 2, "lock_sha256": "stale", "interpreter": "missing"}), encoding="utf-8")
            env = os.environ.copy()
            env["TUTORIAL_RE_DATA_ROOT"] = str(data_root)
            result = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "bootstrap_runtime.py"), "--check", "--json"],
                cwd=ROOT, env=env, capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 2)
            report = json.loads(result.stdout)
            self.assertFalse(report["ready"])
            self.assertFalse(report["metadata_match"])

    def test_installer_update_and_rollback_handles_unicode_path(self) -> None:
        temp_root = Path(tempfile.mkdtemp(prefix="tutorial-re-skill space-ユ"))
        self.addCleanup(lambda: shutil.rmtree(temp_root, ignore_errors=True))
        skills_root = temp_root / "skills root"
        target = skills_root / "reverse-engineer-ai-video-tutorial"
        installer = ROOT / "scripts" / "install_skill.py"

        def run(*extra: str) -> dict:
            return self.run_json(
                str(installer),
                "--source",
                str(ROOT),
                "--skills-root",
                str(skills_root),
                "--target",
                str(target),
                "--json",
                *extra,
            )

        first = run()
        self.assertEqual(first["action"], "install")
        self.assertTrue((target / ".install-receipt.json").is_file())
        self.assertFalse((target / "README.md").exists())
        second = run("--force")
        self.assertEqual(second["action"], "update")
        rollback = run("--rollback")
        self.assertEqual(rollback["action"], "rollback")
        self.assertTrue(target.is_dir())
        self.assertFalse((target / "README.md").exists())

    def test_rollback_restores_target_when_backup_move_fails(self) -> None:
        with tempfile.TemporaryDirectory(prefix="tutorial-re-rollback-failure-") as directory:
            skills_root = Path(directory) / "skills"
            target = skills_root / "reverse-engineer-ai-video-tutorial"
            payload = installer_module.validate_source(ROOT, "reverse-engineer-ai-video-tutorial")
            provenance = installer_module._source_receipt(ROOT)
            installer_module.install(ROOT, target, skills_root, payload, force=False, dry_run=False, provenance=provenance)
            installer_module.install(ROOT, target, skills_root, payload, force=True, dry_run=False, provenance=provenance)
            receipt = json.loads((target / ".install-receipt.json").read_text(encoding="utf-8"))
            backup = Path(receipt["backup"])
            original_replace = installer_module.os.replace

            def fail_backup_move(source: str | os.PathLike[str], destination: str | os.PathLike[str]) -> None:
                if Path(source) == backup and Path(destination) == target:
                    raise OSError("injected backup move failure")
                original_replace(source, destination)

            with mock.patch.object(installer_module.os, "replace", side_effect=fail_backup_move):
                with self.assertRaises(OSError):
                    installer_module.rollback(target, skills_root, dry_run=False)
            self.assertTrue(target.is_dir())
            self.assertTrue((target / ".install-receipt.json").is_file())
            self.assertTrue(backup.is_dir())

    def test_rollback_rejects_tampered_backup_before_swap(self) -> None:
        with tempfile.TemporaryDirectory(prefix="tutorial-re-rollback-tamper-") as directory:
            skills_root = Path(directory) / "skills"
            target = skills_root / "reverse-engineer-ai-video-tutorial"
            payload = installer_module.validate_source(ROOT, "reverse-engineer-ai-video-tutorial")
            provenance = installer_module._source_receipt(ROOT)
            installer_module.install(ROOT, target, skills_root, payload, force=False, dry_run=False, provenance=provenance)
            installer_module.install(ROOT, target, skills_root, payload, force=True, dry_run=False, provenance=provenance)
            receipt = json.loads((target / ".install-receipt.json").read_text(encoding="utf-8"))
            backup = Path(receipt["backup"])
            original = (target / "SKILL.md").read_bytes()
            (backup / "SKILL.md").write_bytes(b"tampered backup")
            with self.assertRaises(SystemExit):
                installer_module.rollback(target, skills_root, dry_run=False)
            self.assertEqual((target / "SKILL.md").read_bytes(), original)
            self.assertTrue(backup.is_dir())
            self.assertTrue(installer_module.verify_install(target, target.name)["ready"])

    def test_rollback_restores_current_target_when_post_swap_verification_fails(self) -> None:
        with tempfile.TemporaryDirectory(prefix="tutorial-re-rollback-postcheck-") as directory:
            skills_root = Path(directory) / "skills"
            target = skills_root / "reverse-engineer-ai-video-tutorial"
            payload = installer_module.validate_source(ROOT, "reverse-engineer-ai-video-tutorial")
            provenance = installer_module._source_receipt(ROOT)
            installer_module.install(ROOT, target, skills_root, payload, force=False, dry_run=False, provenance=provenance)
            installer_module.install(ROOT, target, skills_root, payload, force=True, dry_run=False, provenance=provenance)
            before = (target / "SKILL.md").read_bytes()
            with mock.patch.object(installer_module, "verify_install", side_effect=RuntimeError("injected post-check")):
                with self.assertRaises(RuntimeError):
                    installer_module.rollback(target, skills_root, dry_run=False)
            self.assertEqual((target / "SKILL.md").read_bytes(), before)
            self.assertTrue(installer_module.verify_install(target, target.name)["ready"])

    def test_rollback_postcheck_failure_preserves_distinct_active_and_backup_generations(self) -> None:
        with tempfile.TemporaryDirectory(prefix="tutorial-re-rollback-generations-") as directory:
            root = Path(directory)
            source_a = root / "source-a"
            source_b = root / "source-b"
            ignore = shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache", "node_modules", "out", ".remaining-fixes*")
            shutil.copytree(ROOT, source_a, ignore=ignore)
            shutil.copytree(ROOT, source_b, ignore=ignore)
            (source_a / "SKILL.md").write_bytes((source_a / "SKILL.md").read_bytes() + b"\nGeneration A\n")
            (source_b / "SKILL.md").write_bytes((source_b / "SKILL.md").read_bytes() + b"\nGeneration B\n")
            skills_root = root / "skills"
            target = skills_root / "reverse-engineer-ai-video-tutorial"
            for source in (source_a, source_b):
                payload = installer_module.validate_source(source, "reverse-engineer-ai-video-tutorial")
                installer_module.install(
                    source,
                    target,
                    skills_root,
                    payload,
                    force=source is source_b,
                    dry_run=False,
                    provenance=installer_module._source_receipt(source),
                )
            receipt_b = (target / ".install-receipt.json").read_bytes()
            skill_b = (target / "SKILL.md").read_bytes()
            receipt = json.loads(receipt_b)
            backup = Path(receipt["backup"])
            receipt_a = (backup / ".install-receipt.json").read_bytes()
            skill_a = (backup / "SKILL.md").read_bytes()
            with mock.patch.object(installer_module, "verify_install", side_effect=RuntimeError("injected post-check")):
                with self.assertRaises(RuntimeError):
                    installer_module.rollback(target, skills_root, dry_run=False)
            self.assertEqual((target / ".install-receipt.json").read_bytes(), receipt_b)
            self.assertEqual((target / "SKILL.md").read_bytes(), skill_b)
            self.assertEqual((backup / ".install-receipt.json").read_bytes(), receipt_a)
            self.assertEqual((backup / "SKILL.md").read_bytes(), skill_a)
            self.assertTrue(installer_module.verify_install(target, target.name)["ready"])

    def test_installer_process_race_has_one_winner_and_no_lost_target(self) -> None:
        with tempfile.TemporaryDirectory(prefix="tutorial-re-install-race-") as directory:
            root = Path(directory)
            skills_root = root / "skills"
            target = skills_root / "reverse-engineer-ai-video-tutorial"
            command = [
                PYTHON,
                str(ROOT / "scripts" / "install_skill.py"),
                "--source", str(ROOT),
                "--skills-root", str(skills_root),
                "--target", str(target),
                "--json",
            ]
            first = subprocess.Popen(command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            second = subprocess.Popen(command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            first_out, first_err = first.communicate(timeout=60)
            second_out, second_err = second.communicate(timeout=60)
            results = [(first.returncode, first_out, first_err), (second.returncode, second_out, second_err)]
            self.assertEqual(sum(code == 0 for code, _, _ in results), 1, results)
            self.assertTrue(
                any(("target exists" in err or "already in progress" in err) for code, _, err in results if code != 0),
                results,
            )
            self.assertTrue(installer_module.verify_install(target, target.name)["ready"])

    def test_installer_lock_is_held_and_reusable_after_release(self) -> None:
        with tempfile.TemporaryDirectory(prefix="tutorial-re-lock-") as directory:
            skills_root = Path(directory) / "skills"
            lock = installer_module._acquire_lock(skills_root, "reverse-engineer-ai-video-tutorial")
            try:
                child_env = os.environ.copy()
                child_env["PYTHONPATH"] = str(ROOT / "scripts")
                child = subprocess.run(
                    [
                        PYTHON,
                        "-c",
                        "from pathlib import Path; import sys; from file_lock import acquire; acquire(Path(sys.argv[1]), 'child')",
                        str(lock.path),
                    ],
                    env=child_env,
                    capture_output=True,
                    text=True,
                )
                self.assertNotEqual(child.returncode, 0)
            finally:
                installer_module._release_lock(lock)
            second = installer_module._acquire_lock(skills_root, "reverse-engineer-ai-video-tutorial")
            installer_module._release_lock(second)

    def test_runtime_repair_lock_is_held_and_reusable_after_release(self) -> None:
        with tempfile.TemporaryDirectory(prefix="tutorial-re-runtime-lock-") as directory:
            runtime_root = Path(directory) / "runtime"
            lock = bootstrap_module._acquire_runtime_lock(runtime_root)
            try:
                child_env = os.environ.copy()
                child_env["PYTHONPATH"] = str(ROOT / "scripts")
                child = subprocess.run(
                    [
                        PYTHON,
                        "-c",
                        "from pathlib import Path; import sys; from file_lock import acquire; acquire(Path(sys.argv[1]), 'child')",
                        str(lock.path),
                    ],
                    env=child_env,
                    capture_output=True,
                    text=True,
                )
                self.assertNotEqual(child.returncode, 0)
            finally:
                bootstrap_module._release_runtime_lock(lock)
            second = bootstrap_module._acquire_runtime_lock(runtime_root)
            bootstrap_module._release_runtime_lock(second)

    def test_run_rejects_no_reexec_system_interpreter(self) -> None:
        fake_active = Path(PYTHON).with_name("managed-python.exe")
        with mock.patch.dict(os.environ, {"TUTORIAL_RE_NO_REEXEC": "1"}, clear=False), mock.patch.object(
            run_module, "_ensure_runtime"
        ), mock.patch.object(
            runtime_tools, "managed_runtime_report", return_value={"ready": True, "interpreter": str(fake_active)}
        ), mock.patch.object(runtime_cli, "main", return_value=0), mock.patch.object(run_module.sys, "argv", ["run.py", "validate"]):
            self.assertEqual(run_module.main(), 0)

    def test_no_reexec_marker_does_not_skip_configured_interpreter_validation(self) -> None:
        with mock.patch.dict(
            os.environ,
            {"TUTORIAL_RE_NO_REEXEC": "1", "TUTORIAL_RE_PYTHON": str(Path(PYTHON).with_name("wrong-managed.exe"))},
            clear=False,
        ), mock.patch.object(run_module, "_ensure_runtime"), mock.patch.object(
            runtime_tools, "managed_runtime_report", return_value={"ready": False, "interpreter": ""}
        ), mock.patch.object(run_module.sys, "argv", ["run.py", "validate"]):
            with self.assertRaises(SystemExit) as raised:
                run_module.main()
        self.assertIn("TUTORIAL_RE_PYTHON", str(raised.exception))

    def test_system_runtime_override_emits_explicit_execution_signal(self) -> None:
        stderr = io.StringIO()
        with mock.patch.dict(os.environ, {"TUTORIAL_RE_ALLOW_SYSTEM": "1"}, clear=False), mock.patch.object(
            run_module, "_ensure_runtime"
        ), mock.patch.object(
            run_module, "_maybe_reexec_managed", return_value=None
        ), mock.patch.object(
            runtime_tools, "managed_runtime_report", return_value={"ready": False, "interpreter": "C:/managed/python.exe"}
        ), mock.patch.object(
            runtime_tools, "system_runtime_health", return_value={"ready": True}
        ), mock.patch.object(
            runtime_cli, "main", return_value=0
        ), mock.patch.object(run_module.sys, "argv", ["run.py", "validate"]), redirect_stderr(stderr):
            self.assertEqual(run_module.main(), 0)
        self.assertIn("system runtime override", stderr.getvalue())
        self.assertIn("health=ready", stderr.getvalue())

    def test_doctor_dependency_health_reports_import_failure(self) -> None:
        with tempfile.TemporaryDirectory(prefix="tutorial-re-broken-dependency-") as directory:
            module = Path(directory) / "broken_dependency.py"
            module.write_text("raise RuntimeError('import failed')\n", encoding="utf-8")
            with mock.patch.dict(os.environ, {"PYTHONPATH": str(Path(directory))}, clear=False):
                report = runtime_tools.dependency_health(Path(PYTHON), "broken_dependency", "not-installed", None)
        self.assertTrue(report["available"])
        self.assertFalse(report["import_ok"])
        self.assertFalse(report["ready"])
        self.assertIn("import failed", str(report["error"]))

    def test_github_provenance_binds_exact_tagged_payload_set(self) -> None:
        with tempfile.TemporaryDirectory(prefix="tutorial-re-git-provenance-") as directory:
            source = Path(directory) / "checkout"
            shutil.copytree(
                ROOT,
                source,
                ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache", "node_modules", "out", ".remaining-fixes*")
            )
            def git(*args: str) -> None:
                result = subprocess.run(["git", "-C", str(source), *args], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)

            git("init")
            git("config", "user.email", "test@example.invalid")
            git("config", "user.name", "Test")
            git("config", "core.autocrlf", "true")
            git("add", ".")
            git("commit", "-m", "release")
            git("tag", "v0.0.1")
            git("remote", "add", "origin", "https://github.com/example/reverse-engineer-ai-video-tutorial.git")
            provenance = installer_module._source_receipt(source)
            payload = installer_module.validate_source(source, "reverse-engineer-ai-video-tutorial")
            installer_module._validate_github_source(source, payload, provenance)

            optional = next(path for path in payload if len(path.parts) > 1)
            (source / optional).unlink()
            changed_payload = installer_module.validate_source(source, "reverse-engineer-ai-video-tutorial")
            with self.assertRaises(SystemExit):
                installer_module._validate_github_source(source, changed_payload, provenance)

            restored = subprocess.run(["git", "-C", str(source), "checkout", "--", optional.as_posix()], capture_output=True, text=True)
            self.assertEqual(restored.returncode, 0, restored.stderr)
            skill = source / "SKILL.md"
            original_skill = skill.read_bytes()
            skill.write_bytes(original_skill.replace(b"name: reverse-engineer-ai-video-tutorial", b"name: reverse-engineer-ai-video-tutorial "))
            with self.assertRaises(SystemExit):
                installer_module._validate_github_source(source, installer_module.validate_source(source, "reverse-engineer-ai-video-tutorial"), provenance)
            restored = subprocess.run(["git", "-C", str(source), "checkout", "--", "SKILL.md"], capture_output=True, text=True)
            self.assertEqual(restored.returncode, 0, restored.stderr)
            skill.write_bytes(skill.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
            installer_module._validate_github_source(source, installer_module.validate_source(source, "reverse-engineer-ai-video-tutorial"), provenance)

    def test_ci_runs_remotion_checks_as_failing_steps(self) -> None:
        workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        self.assertIn("run: npm run typecheck\n", workflow)
        self.assertIn("run: npm run compositions\n", workflow)
        install_step = "- name: Install locked test dependencies"
        smoke_step = "- name: Run network-free smoke suite"
        self.assertIn("run: 'python -m pip install --only-binary=:all:", workflow)
        self.assertLess(workflow.index(install_step), workflow.index(smoke_step))

    def test_ci_paths_exist_and_executable_wrappers_are_tracked(self) -> None:
        workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        self.assertNotIn("prepare_framework", workflow)
        for relative in ("install_skill.sh", "prepare_remotion.sh", "prepare_hyperframes.sh"):
            self.assertTrue((ROOT / "scripts" / relative).is_file(), relative)
        result = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "ls-files", "--stage", "--", "skills/reverse-engineer-ai-video-tutorial/scripts/*.sh"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        for line in result.stdout.splitlines():
            self.assertTrue(line.startswith("100755 "), line)

    def test_remotion_fresh_post_publish_failure_quarantines_final_root(self) -> None:
        with tempfile.TemporaryDirectory(prefix="tutorial-re-remotion-fresh-failure-") as directory:
            root = Path(directory) / "toolchain"
            package = prepare_module.SHARED_PACKAGE
            ready = {"ready": True, "state": "ready", "package": package, "error": None}
            broken = {"ready": False, "state": "broken", "package": package, "error": "injected post-publish failure"}

            def fake_run(command: list[str], *, cwd: Path, log_name: str, **_: object) -> None:
                (cwd / log_name).write_text("ok\n", encoding="utf-8")
                if log_name == "toolchain-install.log":
                    (cwd / "node_modules" / ".bin").mkdir(parents=True)
                    (cwd / "node_modules" / ".bin" / "remotion.cmd").write_text("", encoding="utf-8")

            with mock.patch.object(prepare_module, "_inspect_toolchain", side_effect=[
                {"ready": False, "state": "setup_required", "package": {}, "error": "missing"},
                ready,
                broken,
            ]), mock.patch.object(prepare_module, "_run", side_effect=fake_run), mock.patch.object(
                prepare_module, "_check_engine"
            ), mock.patch.object(prepare_module, "require_tool", return_value=["tool"]):
                with self.assertRaises(RuntimeError):
                    prepare_module._ensure_shared_toolchain(root, setup=True)
            self.assertFalse(root.exists())
            self.assertTrue(any(item.name.startswith(".toolchain.failed-") for item in root.parent.iterdir()))

    def test_remotion_update_failure_restores_prior_generation(self) -> None:
        with tempfile.TemporaryDirectory(prefix="tutorial-re-remotion-update-failure-") as directory:
            root = Path(directory) / "toolchain"
            root.mkdir()
            (root / "prior-generation.txt").write_text("prior", encoding="utf-8")
            package = prepare_module.SHARED_PACKAGE
            ready = {"ready": True, "state": "ready", "package": package, "error": None}
            broken = {"ready": False, "state": "broken", "package": package, "error": "injected post-publish failure"}

            def fake_run(command: list[str], *, cwd: Path, log_name: str, **_: object) -> None:
                (cwd / log_name).write_text("ok\n", encoding="utf-8")
                if log_name == "toolchain-install.log":
                    (cwd / "node_modules" / ".bin").mkdir(parents=True)
                    (cwd / "node_modules" / ".bin" / "remotion.cmd").write_text("", encoding="utf-8")

            with mock.patch.object(prepare_module, "_inspect_toolchain", side_effect=[
                broken,
                ready,
                broken,
                ready,
            ]), mock.patch.object(prepare_module, "_run", side_effect=fake_run), mock.patch.object(
                prepare_module, "_check_engine"
            ), mock.patch.object(prepare_module, "require_tool", return_value=["tool"]):
                with self.assertRaises(RuntimeError):
                    prepare_module._ensure_shared_toolchain(root, setup=True)
            self.assertEqual((root / "prior-generation.txt").read_text(encoding="utf-8"), "prior")

    def test_installer_accepts_arbitrary_checkout_name(self) -> None:
        with tempfile.TemporaryDirectory(prefix="tutorial-re-clone-") as directory:
            root = Path(directory)
            source = root / "github-repo-random-name"
            shutil.copytree(ROOT, source, ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache"))
            skills_root = root / "skills"
            target = skills_root / "reverse-engineer-ai-video-tutorial"
            report = self.run_json(
                str(ROOT / "scripts" / "install_skill.py"),
                "--source", str(source), "--skills-root", str(skills_root), "--target", str(target), "--json",
            )
            self.assertEqual(report["action"], "install")
            self.assertTrue((target / "SKILL.md").is_file())
            verified = self.run_json(
                str(ROOT / "scripts" / "install_skill.py"),
                "--skills-root", str(skills_root), "--target", str(target), "--verify", "--json",
            )
            self.assertTrue(verified["ready"])

    def test_installer_fresh_failure_leaves_no_target(self) -> None:
        with tempfile.TemporaryDirectory(prefix="tutorial-re-install-failure-") as directory:
            skills_root = Path(directory) / "skills"
            target = skills_root / "reverse-engineer-ai-video-tutorial"
            payload = installer_module.validate_source(ROOT, "reverse-engineer-ai-video-tutorial")
            provenance = installer_module._source_receipt(ROOT)
            with mock.patch.object(installer_module, "_verify_hashes", side_effect=RuntimeError("injected")):
                with self.assertRaises(RuntimeError):
                    installer_module.install(ROOT, target, skills_root, payload, force=False, dry_run=False, provenance=provenance)
            self.assertFalse(target.exists())
            self.assertFalse(any(".stage-" in item.name for item in skills_root.iterdir()))

    def test_installer_update_failure_restores_prior_target(self) -> None:
        with tempfile.TemporaryDirectory(prefix="tutorial-re-update-failure-") as directory:
            skills_root = Path(directory) / "skills"
            target = skills_root / "reverse-engineer-ai-video-tutorial"
            payload = installer_module.validate_source(ROOT, "reverse-engineer-ai-video-tutorial")
            provenance = installer_module._source_receipt(ROOT)
            installer_module.install(ROOT, target, skills_root, payload, force=False, dry_run=False, provenance=provenance)
            before = (target / "SKILL.md").read_bytes()
            with mock.patch.object(installer_module, "_write_receipt", side_effect=RuntimeError("injected")):
                with self.assertRaises(RuntimeError):
                    installer_module.install(ROOT, target, skills_root, payload, force=True, dry_run=False, provenance=provenance)
            self.assertEqual((target / "SKILL.md").read_bytes(), before)
            self.assertTrue((target / ".install-receipt.json").is_file())

    def test_installer_verify_rejects_unexpected_payload_file(self) -> None:
        with tempfile.TemporaryDirectory(prefix="tutorial-re-unexpected-") as directory:
            skills_root = Path(directory) / "skills"
            target = skills_root / "reverse-engineer-ai-video-tutorial"
            installer = ROOT / "scripts" / "install_skill.py"
            first = self.run_json(
                str(installer), "--source", str(ROOT), "--skills-root", str(skills_root), "--target", str(target), "--json"
            )
            self.assertEqual(first["action"], "install")
            (target / "unexpected.txt").write_text("tamper", encoding="utf-8")
            result = subprocess.run(
                [PYTHON, str(installer), "--skills-root", str(skills_root), "--target", str(target), "--verify", "--json"],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("payload set mismatch", result.stderr)

    def test_installed_entrypoint_preserves_receipt_verifiability(self) -> None:
        with tempfile.TemporaryDirectory(prefix="tutorial-re-bytecode-") as directory:
            skills_root = Path(directory) / "skills"
            target = skills_root / "reverse-engineer-ai-video-tutorial"
            installer = ROOT / "scripts" / "install_skill.py"
            self.run_json(
                str(installer), "--source", str(ROOT), "--skills-root", str(skills_root), "--target", str(target), "--json"
            )
            completed = subprocess.run(
                [PYTHON, str(target / "scripts" / "run.py"), "--runtime", "system", "--help"],
                cwd=Path(directory),
                capture_output=True,
                text=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertFalse(any(path.name == "__pycache__" for path in target.rglob("__pycache__")))
            verified = self.run_json(
                str(installer), "--skills-root", str(skills_root), "--target", str(target), "--verify", "--json"
            )
            self.assertTrue(verified["ready"])

    def test_doctor_rejects_unsupported_python_and_missing_workspace(self) -> None:
        missing = Path(tempfile.mkdtemp(prefix="tutorial-re-doctor-missing-")) / "not-created"
        with mock.patch.object(
            runtime_doctor,
            "python_runtime_health",
            return_value={"available": True, "supported": False, "version": "3.15.0", "error": None},
        ):
            report = runtime_doctor.doctor_report(workspace_root=missing)
        self.assertFalse(report["profiles"]["base"]["ready"])
        self.assertIn("python", report["profiles"]["base"]["missing"])
        self.assertFalse(missing.exists())

    def test_doctor_omitted_paths_are_not_checked(self) -> None:
        report = runtime_doctor.doctor_report()
        self.assertEqual(report["probes"]["workspace"]["state"], "not_checked")
        self.assertEqual(report["probes"]["cache"]["state"], "not_checked")
        self.assertEqual(report["profiles"]["base"]["state"], "needs_context")
        self.assertNotIn("workspace", report["profiles"]["base"]["missing"])
        self.assertNotIn("cache", report["profiles"]["base"]["missing"])
        self.assertEqual(report["frameworks"]["remotion"]["state"], "not_checked")
        self.assertEqual(report["frameworks"]["hyperframes"]["state"], "not_checked")
        self.assertEqual(report["tools"]["yt-dlp"]["source"], "not_checked")
        self.assertEqual(report["profiles"]["youtube-guide"]["state"], "not_checked")

    def test_system_profile_uses_feature_probe_and_scoped_path_state(self) -> None:
        with tempfile.TemporaryDirectory(prefix="tutorial-re-adaptive-") as directory:
            root = Path(directory)
            workspace = root / "workspace"
            cache = workspace / "cache"
            cache.mkdir(parents=True)
            report = runtime_doctor.doctor_report(
                "base",
                runtime="system",
                workspace_root=workspace,
                cache_root=cache,
            )
        self.assertEqual(report["environment"]["selected"], "system_compatible")
        self.assertEqual(report["dependencies"]["Pillow"]["verified"], "feature_probe")
        self.assertEqual(report["profiles"]["base"]["state"], "ready_with_warnings")

    def test_doctor_rejects_cache_outside_workspace(self) -> None:
        with tempfile.TemporaryDirectory(prefix="tutorial-re-path-scope-") as directory:
            root = Path(directory)
            workspace = root / "workspace"
            cache = root / "outside-cache"
            workspace.mkdir()
            cache.mkdir()
            report = runtime_doctor.doctor_report(
                "base",
                runtime="system",
                workspace_root=workspace,
                cache_root=cache,
            )
        self.assertEqual(report["state"], "blocked")
        self.assertIn("cache root inside the workspace", report["next_action"])

    def test_yt_dlp_standalone_route_wins_over_python_module(self) -> None:
        with tempfile.TemporaryDirectory(prefix="tutorial-re-ytdlp-route-") as directory:
            fake = Path(directory) / ("yt-dlp.exe" if os.name == "nt" else "yt-dlp")
            fake.write_text("", encoding="utf-8")
            with mock.patch.object(runtime_tools.shutil, "which", return_value=str(fake)), mock.patch.object(
                runtime_tools.importlib.util, "find_spec", return_value=object()
            ):
                result = runtime_tools.resolve_tool("yt-dlp", python_module="yt_dlp")
        self.assertEqual(result.source, "path")
        self.assertEqual(result.command, (str(fake),))

    def test_runtime_profile_dispatch_handles_equals_and_media_commands(self) -> None:
        self.assertEqual(run_module._profile_for_command("ingest", ["--video-url=https://example.test/v"]), "youtube-guide")
        self.assertEqual(run_module._profile_for_command("ingest", ["--video-file", "clip.mp4"]), "local-guide")
        self.assertEqual(run_module._profile_for_command("extract-detail", []), "local-guide")
        self.assertEqual(run_module._profile_for_command("qa-clip", []), "local-guide")

    def test_system_runtime_health_uses_selected_interpreter_probe(self) -> None:
        selected = Path(PYTHON)
        unavailable = runtime_tools.ToolResolution("test", None, None, "missing", verified=False)
        with mock.patch.object(
            runtime_tools,
            "python_runtime_health",
            return_value={"available": True, "supported": False, "version": "3.15.0", "error": None},
        ) as probe, mock.patch.object(
            runtime_tools,
            "compatible_dependency_health",
            return_value={"ready": True},
        ), mock.patch.object(runtime_tools, "probe_tool", return_value=unavailable):
            report = runtime_tools.system_runtime_health(selected, "base")
        probe.assert_called_once_with(selected)
        self.assertFalse(report["ready"])
        self.assertIn("python", report["missing"])

    def test_runtime_root_rejects_relative_and_broad_overrides(self) -> None:
        with mock.patch.dict(os.environ, {"TUTORIAL_RE_DATA_ROOT": "relative-runtime"}, clear=False):
            with self.assertRaises(ValueError):
                runtime_tools.runtime_data_root()
        with mock.patch.dict(os.environ, {"TUTORIAL_RE_DATA_ROOT": str(Path.home())}, clear=False):
            with self.assertRaises(ValueError):
                runtime_tools.runtime_data_root()

    def test_engine_check_compares_minor_and_patch(self) -> None:
        with mock.patch.object(
            prepare_module,
            "probe_tool",
            return_value=runtime_tools.ToolResolution("node", ("node",), "node", "test", "v18.0.0", True),
        ):
            with self.assertRaises(RuntimeError):
                prepare_module._check_engine("node", ">=18.17.0")
        with mock.patch.object(
            prepare_module,
            "probe_tool",
            return_value=runtime_tools.ToolResolution("node", ("node",), "node", "test", "v18.17.0", True),
        ):
            prepare_module._check_engine("node", ">=18.17.0")

    def test_portable_source_ids_reject_reserved_and_invalid_names(self) -> None:
        for source_id in ("CON", "report.", "bad*name", "bad\nname"):
            with self.subTest(source_id=source_id):
                with self.assertRaises(SystemExit):
                    prepare_module._validate_source_id(source_id)

    def test_doctor_marks_broken_executable_unavailable(self) -> None:
        with tempfile.TemporaryDirectory(prefix="tutorial-re-bad-tool-") as directory:
            root = Path(directory)
            if os.name == "nt":
                fake = root / "fake-ffmpeg.cmd"
                fake.write_text("@exit /b 7\n", encoding="utf-8")
            else:
                fake = root / "fake-ffmpeg"
                fake.write_text("#!/bin/sh\nexit 7\n", encoding="utf-8")
                fake.chmod(0o700)
            with mock.patch.dict(os.environ, {"TUTORIAL_RE_FFMPEG": str(fake)}, clear=False):
                result = runtime_tools.probe_tool("ffmpeg")
        self.assertFalse(result.available)
        self.assertIsNotNone(result.error)

    def test_platform_data_root_and_remotion_containment(self) -> None:
        with tempfile.TemporaryDirectory(prefix="tutorial-re-platform-") as directory:
            with mock.patch.object(runtime_tools.platform, "system", return_value="Linux"), mock.patch.dict(
                os.environ, {"XDG_DATA_HOME": "relative-data"}, clear=False
            ):
                root = runtime_tools.runtime_data_root()
            self.assertEqual(root, Path.home() / ".local" / "share" / "reverse-engineer-ai-video-tutorial")
            with mock.patch.object(runtime_tools.platform, "system", return_value="Darwin"):
                self.assertEqual(runtime_tools.runtime_data_root(), Path.home() / "Library" / "Application Support" / "reverse-engineer-ai-video-tutorial")
            result = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "prepare_remotion.py"), "--repo-root", directory, "--source-id", ".."],
                capture_output=True, text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            escaped = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "prepare_remotion.py"), "--repo-root", directory, "--source-id", "safe", "--destination", ".."],
                capture_output=True, text=True,
            )
            self.assertNotEqual(escaped.returncode, 0)

    def test_remotion_payload_is_lean_and_shared_toolchain_is_explicit(self) -> None:
        report = self.run_json(
            str(ROOT / "scripts" / "install_skill.py"),
            "--source", str(ROOT), "--dry-run", "--json",
        )
        self.assertFalse(any(path.startswith("assets/frameworks/remotion-template/") for path in (item["path"] for item in report["files"])))
        package = prepare_module.SHARED_PACKAGE
        self.assertEqual(package["dependencies"]["remotion"], prepare_module.REMOTION_VERSION)
        self.assertNotIn("package-lock.json", prepare_module.SCAFFOLD_FILES)
        self.assertNotIn("start-studio.sh", prepare_module.SCAFFOLD_FILES)
        self.assertGreaterEqual(int(package["engines"]["node"].split(">=")[1].split(".")[0]), 18)
        self.assertGreaterEqual(int(package["engines"]["npm"].split(">=")[1].split(".")[0]), 9)

    def test_installer_report_matches_canonical_payload_set(self) -> None:
        payload = {path.as_posix() for path in installer_module.validate_source(ROOT, ROOT.name)}
        report = self.run_json(str(ROOT / "scripts" / "install_skill.py"), "--source", str(ROOT), "--dry-run", "--json")
        self.assertEqual(payload, {item["path"] for item in report["files"]})

    def test_remotion_lock_input_is_code_bound(self) -> None:
        package, lock = prepare_module._reviewed_package_and_lock()
        self.assertEqual(lock["packages"][""]["dependencies"], package["dependencies"])
        with mock.patch.object(prepare_module, "REVIEWED_LOCK_SHA256", "tampered"):
            with self.assertRaises(RuntimeError):
                prepare_module._reviewed_package_and_lock()


if __name__ == "__main__":
    unittest.main()
