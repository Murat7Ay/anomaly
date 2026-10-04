"""Forward migrations ("upcasters") for stored contract specs.

Contracts and decision snapshots are stored for many years. When the spec format evolves, never edit
stored JSON in place: bump `CURRENT_SCHEMA_VERSION`, add an upcaster from the previous version, and
every reader goes through `load_spec()`. Old records stay byte-identical (their hashes stay valid)
while the code only ever sees the current model.

Adding version N+1:
    1. change ContractSpec, set CURRENT_SCHEMA_VERSION = N+1 (and the Literal on schema_version)
    2. register  UPCASTERS[N] = lambda raw: {...raw, "schema_version": N+1, <transformations>}
    3. add a fixture of a real version-N spec to tests/domain/test_contract_migrations.py
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from loadguard.domain.contract import ContractSpec

CURRENT_SCHEMA_VERSION = 1

Upcaster = Callable[[dict[str, Any]], dict[str, Any]]
UPCASTERS: dict[int, Upcaster] = {
    # Example of the pattern (version 0 = pre-release drafts that called slots "deliveries"):
    0: lambda raw: {
        **{k: v for k, v in raw.items() if k != "deliveries"},
        "slots": raw.get("slots", raw.get("deliveries", [])),
        "schema_version": 1,
    },
}


class SpecMigrationError(ValueError):
    pass


def upcast(raw: dict[str, Any]) -> dict[str, Any]:
    version = int(raw.get("schema_version", 0))
    if version > CURRENT_SCHEMA_VERSION:
        raise SpecMigrationError(
            f"spec schema_version {version} is newer than this software ({CURRENT_SCHEMA_VERSION}); upgrade first"
        )
    data = dict(raw)
    while version < CURRENT_SCHEMA_VERSION:
        step = UPCASTERS.get(version)
        if step is None:
            raise SpecMigrationError(f"no upcaster from schema_version {version}")
        data = step(data)
        version = int(data["schema_version"])
    return data


def load_spec(raw: dict[str, Any]) -> ContractSpec:
    return ContractSpec.model_validate(upcast(raw))
