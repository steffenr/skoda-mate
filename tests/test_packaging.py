"""The packaging files: the Unraid template and the Community Applications repository profile.

Community Apps reads both straight out of this repository (nothing is uploaded), so a missing tag or a dead
raw.githubusercontent.com URL only surfaces when someone re-runs the submission scan. These tests keep the files in the
shape CA requires and tie them to the rest of the repository.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "unraid" / "skoda-mate.xml"
PROFILE = ROOT / "ca_profile.xml"
IMAGE = "steffenr/skoda-mate"
RAW = f"https://raw.githubusercontent.com/{IMAGE}/main/"

# What the CA parser needs from a Docker template, plus the fields the submission review reads (docs: /submit/help).
REQUIRED_TEMPLATE_TAGS = (
    "Name",
    "Repository",
    "Registry",
    "Network",
    "WebUI",
    "Overview",
    "Category",
    "Support",
    "Project",
    "TemplateURL",
    "ReadMe",
    "Icon",
    "License",
)
REQUIRED_PROFILE_TAGS = ("Profile", "Icon", "WebPage")


def text(root: ET.Element, tag: str) -> str:
    element = root.find(tag)
    return "" if element is None or element.text is None else element.text.strip()


def raw_urls(*paths: Path) -> list[str]:
    return re.findall(r"https://raw\.githubusercontent\.com/[^\s<>\"]+", "\n".join(p.read_text() for p in paths))


def test_profile_lives_in_the_repository_root_with_a_real_profile_section():
    """CA blocks submission finalization without ca_profile.xml and a non-empty <Profile>."""
    root = ET.parse(PROFILE).getroot()
    assert root.tag == "CommunityApplications"
    for tag in REQUIRED_PROFILE_TAGS:
        assert text(root, tag), f"ca_profile.xml needs a non-empty <{tag}>"
    assert len(text(root, "Profile")) > 80  # a sentence, not a placeholder
    assert "YOUR_" not in PROFILE.read_text()  # starter-repository placeholders


def test_template_carries_every_tag_community_apps_scans():
    root = ET.parse(TEMPLATE).getroot()
    assert root.tag == "Container" and root.get("version") == "2"
    for tag in REQUIRED_TEMPLATE_TAGS:
        assert text(root, tag), f"unraid/skoda-mate.xml needs a non-empty <{tag}>"
    assert text(root, "Repository").startswith(f"{IMAGE}:")
    assert text(root, "TemplateURL") == f"{RAW}unraid/skoda-mate.xml"
    assert text(root, "WebUI").startswith("http://[IP]:[PORT:")  # CA replaces the port from the <Config> entry
    assert text(root, "Category").startswith("HomeAutomation:")


def test_every_hot_linked_url_points_at_a_file_in_this_repository():
    """Icons, screenshots and the readme are hot-linked from main; CA shows a broken image when a file moves."""
    urls = raw_urls(TEMPLATE, PROFILE)
    assert urls
    for url in urls:
        assert url.startswith(RAW), f"{url} must live in this repository on main"
        assert (ROOT / url.removeprefix(RAW)).is_file(), f"{url} does not resolve to a file"


def test_configs_are_unique_and_complete():
    configs = ET.parse(TEMPLATE).getroot().findall("Config")
    targets = [config.get("Target") for config in configs]
    assert len(targets) == len(set(targets)), "two <Config> entries share a target"
    for config in configs:
        for attribute in ("Name", "Target", "Type", "Display", "Required", "Mask"):
            assert config.get(attribute) is not None, f"<Config {config.get('Name')}> lacks {attribute}"
    assert {config.get("Type") for config in configs} <= {"Port", "Path", "Variable"}
    assert {config.get("Target") for config in configs if config.get("Type") == "Port"} == {"8080"}


def test_template_variables_are_variables_the_app_reads():
    """A typo here would show up as a setting that silently does nothing."""
    source = (ROOT / "skoda_mate" / "config.py").read_text()
    read_by_app = set(re.findall(r'g\(\s*"([A-Z_]+)"', source))
    assert "DB_PATH" in read_by_app
    variables = {
        config.get("Target") for config in ET.parse(TEMPLATE).getroot().findall("Config") if config.get("Type") == "Variable"
    }
    assert variables <= read_by_app


def test_image_name_is_the_same_everywhere():
    for path in (
        "README.md",
        "docker-compose.yml",
        "unraid/docker-compose.yml",
        "unraid/skoda-mate.xml",
        "ca_profile.xml",
        "docs/UNRAID.md",
    ):
        assert IMAGE in (ROOT / path).read_text(), f"{path} does not mention {IMAGE}"
