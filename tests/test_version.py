"""The version the app reports, and how a release computes the next one."""
import shutil
import subprocess
from pathlib import Path

import pytest

from skoda_mate import _read_version

SCRIPT = Path(__file__).parent.parent / "scripts" / "next-version.sh"


def test_build_version_file_wins_over_the_source_version(tmp_path):
    f = tmp_path / "BUILD_VERSION"
    assert _read_version(f, "0.1.0") == "0.1.0"  # no file: a source checkout
    f.write_text("0.1.1\n")
    assert _read_version(f, "0.1.0") == "0.1.1"  # the Docker image, stamped from the release tag
    f.write_text("  \n")
    assert _read_version(f, "0.1.0") == "0.1.0"  # an empty stamp never blanks the version


def _repo(tmp_path, version, tags=()):
    run = lambda *a: subprocess.run(a, cwd=tmp_path, check=True, capture_output=True)  # noqa: E731
    run("git", "init", "-q")
    (tmp_path / "pyproject.toml").write_text(f'[project]\nname = "x"\nversion = "{version}"\n\n[dependency-groups]\nversion = "9.9.9"\n')
    run("git", "add", "-A")
    run("git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init")
    for tag in tags:
        run("git", "tag", tag)
    return tmp_path


def _next(repo, bump):
    return subprocess.run(["bash", str(SCRIPT), bump], cwd=repo, capture_output=True, text=True)


needs_git = pytest.mark.skipif(not (shutil.which("git") and shutil.which("bash")), reason="needs git and bash")


@needs_git
@pytest.mark.parametrize(
    "version, tags, bump, expected",
    [
        ("0.1.0", [], "patch", "0.1.1"),  # first release: from pyproject.toml
        ("0.1.0", ["0.1.1"], "patch", "0.1.2"),  # a release made in the GitHub UI (tag without "v", files not bumped)
        ("0.1.0", ["v0.1.1", "v0.1.10", "v0.1.9"], "patch", "0.1.11"),  # numeric, not alphabetical, order
        ("0.1.0", ["0.1.1"], "minor", "0.2.0"),
        ("0.3.0", ["v0.2.5"], "major", "1.0.0"),  # pyproject ahead of the tags
        ("0.1.0", ["backup/x", "v0.2.0-rc1", "nightly"], "patch", "0.1.1"),  # other tags are ignored
    ],
)
def test_next_version_starts_from_the_highest_release(tmp_path, version, tags, bump, expected):
    r = _next(_repo(tmp_path, version, tags), bump)
    assert r.returncode == 0, r.stderr
    assert r.stdout.split() == [f"next={expected}", f"tag=v{expected}"]


@needs_git
def test_next_version_refuses_a_bad_bump_or_missing_version(tmp_path):
    repo = _repo(tmp_path, "0.1.0")
    assert _next(repo, "huge").returncode != 0
    (repo / "pyproject.toml").write_text('[project]\nname = "x"\n')
    r = _next(repo, "patch")
    assert r.returncode != 0 and "No version" in r.stderr
