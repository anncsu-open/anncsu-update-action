#!/usr/bin/env python3

# Anncsu Update Action
# This action extracts specified tables from a DuckDB database file
# and saves them in the desired format (GPKG or Parquet).
# two versions of the table are extracted: current and previous (if available)
# where previous refers to the version in the previous commit.

import json
from pathlib import Path

from actions import context, core

# ANNCSU API related imports
from anncsu.pa import AnncsuConsultazione as Anncsu

# Step 1: Client Assertion
from anncsu.common.config import ClientAssertionSettings, APIType
from anncsu.common import create_client_assertion

# Step 2: Token Exchange
from anncsu.common import PDNDAuthManager
from anncsu.common.session import get_config_dir

# Step 3: API Authentication
from anncsu.common import Security

import functions
from geodiff_models import GeodiffFile


version: str = core.get_version()
core.info(f"Starting Anncsu Update Action - \033[32;1m{version}")


# Inputs

geodiff_report: str = core.get_input("geodiff_report", True)
core.info(f"geodiff_report: \033[36;1m{geodiff_report}")
token: str = core.get_input("token", True)

# Debug

with core.group("uv"):
    functions.check_output("uv -V", False)
    functions.check_output("uv python dir", False)


ctx = {k: v for k, v in vars(context).items() if not k.startswith("__")}
del ctx["os"]
with core.group("GitHub Context Data"):
    core.debug(json.dumps(ctx, indent=4))


# Action Logic

core.info("Update ANNCU DB from geodiff report...")


def _call_anncsu_api_for_entry(entry, anncsu_client: Anncsu) -> bool:
    """Placeholder to call the ANNCSU API for a single GeodiffEntry.

    This function should be replaced with the real integration. For now it
    logs the intended action and returns True to indicate success.
    """
    try:
        action = entry.type
        table = entry.table
        core.info(f"Preparing ANNCSU API call: action={action} table={table}")
        # TODO: implement real ANNCSU API calls (insert/update/delete)
        # Example placeholder behaviour:
        if action == "insert":
            core.info(f"(placeholder) Insert {len(entry.changes)} values into {table}")
        elif action == "update":
            core.info(f"(placeholder) Update {len(entry.changes)} values in {table}")
        elif action == "delete":
            core.info(f"(placeholder) Delete {len(entry.changes)} values from {table}")
        else:
            core.warn(f"Unknown action type: {action}")
            return False
        return True
    except Exception as exc:  # pragma: no cover - defensive
        core.error(f"Error calling ANNCSU API for entry: {exc}")
        return False


# Load and validate the geodiff report
report_path = Path(geodiff_report)
geodiff_obj = None
if report_path.exists():
    core.info(f"Found geodiff report file: {report_path}")
    try:
        geodiff_obj = GeodiffFile.from_path(report_path)
    except Exception as exc:
        core.error(f"Failed to parse geodiff report file: {exc}")
else:
    core.info("geodiff_report input does not point to a file; attempting to parse as JSON text")
    try:
        geodiff_obj = GeodiffFile.from_json_text(geodiff_report)
    except Exception as exc:
        core.error(f"Failed to parse geodiff_report input as JSON: {exc}")

if geodiff_obj is None:
    core.set_failed("Could not load or validate geodiff report; aborting")
    raise SystemExit(1)

# then authenticate with ANNCSU API
core.info("Authenticating with ANNCSU API...")
try:
    # Step 1: Create client assertion (JWT)
    settings = ClientAssertionSettings()  # Loads from env/.env
    accessi_config = settings.to_config(APIType.ACCESSI)
    client_assertion = create_client_assertion(accessi_config)

    # Step 2: Exchange for access token
    manager = PDNDAuthManager(
        settings=settings,
        token_endpoint=accessi_config.audience,
        api_type=APIType.ACCESSI,
        session_persistence=True,
        config_dir=get_config_dir(),
    )
    # Force token retrieval (will save session automatically)
    access_token = manager.get_access_token()

    # Step 3: Use access token for API calls
    security = Security(bearer=access_token)
except Exception as exc:
    core.set_failed(f"Failed to authenticate with ANNCSU API: {exc}")
    raise SystemExit(1) from exc

# instantiate anncsu sdk client
core.info("Instantiating ANNCSU SDK client...")
try:
    with Anncsu(security=security) as anncsu_client:
        core.info("ANNCSU SDK client instantiated successfully")

        # Dispatch entries to ANNCSU API handlers
        results = []
        for entry in geodiff_obj.geodiff:
            ok = _call_anncsu_api_for_entry(entry, anncsu_client)
            results.append((entry.type, ok))

        success = all(r for _, r in results)
        if not success:
            core.warn("One or more ANNCSU API calls failed (see logs)")

        # Track temp files for cleanup
        temp_files_to_cleanup: list[str] = []

except Exception as exc:
    core.set_failed(f"Failed to instantiate ANNCSU SDK client: {exc}")
    raise SystemExit(1) from exc

# Initialize variables


core.info("Anncsu Update Action completed")
print("\033[32;1mAnncsu Update Action completed successfully\033[0m")
