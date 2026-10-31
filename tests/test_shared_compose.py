"""compose.shared.yml, the simulator both apps use in shared mode (README: Shared mode)."""
from pathlib import Path

import yaml

from fakecspace.store import TENANT_IDS

COMPOSE = yaml.safe_load((Path(__file__).parent.parent / "compose.shared.yml").read_text())


def test_every_museum_has_its_host_name_on_the_shared_network() -> None:
    service = COMPOSE["services"]["fakecspace"]
    aliases = service["networks"]["shared"]["aliases"]
    assert sorted(aliases) == sorted(f"{museum}.fakecspace" for museum in TENANT_IDS)


def test_the_network_has_the_fixed_name_the_apps_join() -> None:
    assert COMPOSE["networks"]["shared"]["name"] == "fakecspace-shared"
    assert COMPOSE["name"] == "fakecspace-shared"


def test_published_on_localhost_only() -> None:
    assert all(port.startswith("127.0.0.1:") for port in COMPOSE["services"]["fakecspace"]["ports"])
