"""Checks that system.yaml (at the repository root) describes this service as the code is.

system.schema.json checks the file's shape in CI; these tests check its content:
the environment variables, paths and calls must match the code, so the file
cannot silently drift away from it.
"""
import re
from pathlib import Path

import yaml

SERVICE_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = SERVICE_DIR.parents[1]
SERVICE = SERVICE_DIR.name
SYSTEM = yaml.safe_load((REPO_ROOT / "system.yaml").read_text())
ME = SYSTEM["services"][SERVICE]
ENV_READ = re.compile(r"""os\.environ(?:\.get\(|\[)\s*["']([A-Z][A-Z0-9_]*)["']""")


def env_vars_read_by_the_code():
    names = set()
    for source in SERVICE_DIR.glob("*.py"):
        names.update(ENV_READ.findall(source.read_text()))
    return names


def test_system_yaml_lists_exactly_the_environment_variables_the_code_reads():
    assert set(ME["env"]) == env_vars_read_by_the_code()


def test_the_paths_in_system_yaml_exist():
    assert (REPO_ROOT / ME["path"]).resolve() == SERVICE_DIR
    assert (REPO_ROOT / ME["openapi"]).is_file()
    assert (REPO_ROOT / ME["migrations"]).is_dir()


def test_port_default_matches_the_code_and_the_dockerfile():
    assert ME["port_default"] == ME["env"]["PORT"]["default"]
    app_source = (SERVICE_DIR / "app.py").read_text()
    assert f'os.environ.get("PORT", "{ME["port_default"]}")' in app_source
    assert f"PORT={ME['port_default']}" in (SERVICE_DIR / "Dockerfile").read_text()


def test_every_called_endpoint_is_in_the_called_services_openapi():
    for call in ME.get("calls", []):
        called = SYSTEM["services"][call["service"]]
        paths = yaml.safe_load((REPO_ROOT / called["openapi"]).read_text())["paths"]
        for endpoint in call["endpoints"]:
            method, path = endpoint.split(" ", 1)
            assert method.lower() in paths.get(path, {}), f"{endpoint} is not in {called['openapi']}"
        assert call["url_env"] in ME["env"]
