"""Škoda Mate."""
from pathlib import Path

# The source version. release.yml rewrites this line and checks it verbatim: keep it exactly `__version__ = "X.Y.Z"`.
__version__ = "0.1.3"


def _read_version(stamp: Path, source: str) -> str:
    """The release a Docker image was built for: docker-publish.yml stamps it from the git tag into BUILD_VERSION, so
    the image shows the right version even for a release whose files were never bumped. Elsewhere: the source version."""
    try:
        return stamp.read_text().strip() or source
    except OSError:
        return source


__version__ = _read_version(Path(__file__).with_name("BUILD_VERSION"), __version__)
