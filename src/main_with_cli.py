#!/usr/bin/env python3

# Anncsu Update Action
# This action updates the ANNCSU database by processing geodiff reports
# and calling the ANNCSU CLI to sync coordinate changes.

from __future__ import annotations

import json
import base64
from pathlib import Path
from dataclasses import dataclass
from typing import Protocol, Any, runtime_checkable
from unittest.mock import MagicMock

from geodiff_models import GeodiffFile, GeodiffEntry

# using ANNCSU-SDK to query the database for existing records and to perform updates via CLI calls
from anncsu.common import Security
from anncsu.pa import AnncsuConsultazione

# ============================================================================
# Protocol definitions for dependency injection
# ============================================================================


@runtime_checkable
class LoggerProtocol(Protocol):
    """Protocol for logging operations."""

    def get_version(self) -> str: ...
    def info(self, message: str) -> None: ...
    def debug(self, message: str) -> None: ...
    def warn(self, message: str) -> None: ...
    def error(self, message: str) -> None: ...
    def set_failed(self, message: str) -> None: ...
    def group(self, name: str) -> Any: ...
    def get_input(self, name: str, required: bool = False) -> str: ...


@runtime_checkable
class SettingsProtocol(Protocol):
    """Protocol for settings."""

    codice_comune: str
    coordinate_distance_threshold: float
    dry_run: bool

    def model_dump_json(self) -> str: ...


@runtime_checkable
class CliRunnerProtocol(Protocol):
    """Protocol for CLI runner."""

    def invoke(self, app: Any, args: list[str]) -> Any: ...


@runtime_checkable
class GeoDiffProtocol(Protocol):
    """Protocol for GeoDiff operations."""

    def create_wkb_from_gpkg_header(self, data: bytes) -> list[bytes]: ...


@runtime_checkable
class GeometryProtocol(Protocol):
    """Protocol for geometry objects."""

    is_valid: bool
    geom_type: str
    coords: Any


# ============================================================================
# Column index constants for geodiff entries
# ============================================================================

# column names used to look up the indices in the geodiff schema
COLUMN_NAME_ADDRESS_ID = "PROGRESSIVO_ACCESSO"
COLUMN_NAME_GEOMETRY = "geom"
COLUMN_NAME_ROAD_ID = "PROGRESSIVO_NAZIONALE"
COLUMN_NAME_PLUGIN_SCORE = "PLUGIN_SCORE"
COLUMN_NAME_PLUGIN_GEOCODER = "PLUGIN_GEOCODER"
# default column indices for geodiff entries (overridden by load_geodiff_schema)
COLUMN_ADDRESS_ID = 0  # PROGRESSIVO_ACCESSO
COLUMN_GEOMETRY = 1
COLUMN_ROAD_ID = 4  # PROGRESSIVO_NAZIONALE
COLUMN_PLUGIN_SCORE = 20  # PLUGIN_SCORE (if available in the geodiff report)
COLUMN_PLUGIN_GEOCODER = 21  # PLUGIN_GEOCODER (if available in the geodiff report)


# ============================================================================
# Data classes for structured results
# ============================================================================


@dataclass
class Coordinates:
    """Represents extracted X,Y coordinates."""

    x: float
    y: float


@dataclass
class EntryResult:
    """Result of processing a single geodiff entry."""

    entry_type: str
    success: bool
    error_message: str | None = None


# ============================================================================
# Dry run support
# ============================================================================


@dataclass
class DryRunCliResult:
    """Fake CLI result returned in dry run mode."""

    exit_code: int = 0
    output: str = ""


class DryRunCliRunner:
    """CLI runner that logs commands instead of executing them.

    The "pa accesso" query returns a fake record without coordinates, so the
    coordinate update command is always reached and logged.
    """

    def __init__(self, logger: LoggerProtocol):
        self.logger = logger
        self.calls: list[list[str]] = []

    def invoke(self, app: Any, args: list[str]) -> DryRunCliResult:
        self.calls.append(args)
        self.logger.info(f"[DRY RUN] would invoke ANNCSU CLI: {' '.join(args)}")
        if args[:2] == ["pa", "accesso"]:
            prognazacc = args[args.index("--prognazacc") + 1] if "--prognazacc" in args else ""
            output = json.dumps([{"prognazacc": prognazacc, "coordX": None, "coordY": None}])
        else:
            output = json.dumps({"dry_run": True})
        return DryRunCliResult(exit_code=0, output=output)


# ============================================================================
# Geometry parsing functions (now separately testable)
# ============================================================================


def decode_gpkg_geometry(
    gpkg_base64: str,
    geodiff: GeoDiffProtocol,
    wkb_loader: Any,
) -> GeometryProtocol:
    """Decode a base64-encoded GPKG geometry to a shapely geometry.

    Args:
        gpkg_base64: Base64-encoded GPKG geometry header
        geodiff: GeoDiff instance for WKB conversion
        wkb_loader: shapely.wkb.loads function

    Returns:
        Decoded shapely geometry object

    Raises:
        ValueError: If geometry cannot be decoded
    """
    decoded_gpkg_geom = base64.b64decode(gpkg_base64)
    wkb_geom = geodiff.create_wkb_from_gpkg_header(decoded_gpkg_geom)
    return wkb_loader(wkb_geom)


def extract_coordinates_from_geometry(geometry: GeometryProtocol) -> Coordinates:
    """Extract X,Y coordinates from a Point geometry.

    Args:
        geometry: Shapely geometry object

    Returns:
        Coordinates object with x,y values

    Raises:
        ValueError: If geometry is invalid or not a Point
    """
    if not geometry.is_valid:
        raise ValueError("Invalid geometry")

    if geometry.geom_type != "Point":
        raise ValueError(f"Geometry is not a Point, got: {geometry.geom_type}")

    x, y = list(geometry.coords)[0]
    return Coordinates(x=x, y=y)


def parse_gpkg_to_coordinates(
    gpkg_base64: str,
    geodiff: GeoDiffProtocol,
    wkb_loader: Any,
) -> Coordinates:
    """Parse a GPKG geometry string to X,Y coordinates.

    This is the main entry point for geometry parsing, combining
    decode and coordinate extraction.

    Args:
        gpkg_base64: Base64-encoded GPKG geometry
        geodiff: GeoDiff instance
        wkb_loader: shapely.wkb.loads function

    Returns:
        Coordinates object

    Raises:
        ValueError: If parsing fails
    """
    geometry = decode_gpkg_geometry(gpkg_base64, geodiff, wkb_loader)
    return extract_coordinates_from_geometry(geometry)


# ============================================================================
# Entry processing functions
# ============================================================================


def extract_entry_data(entry: GeodiffEntry) -> tuple[int | None, int | None, str | None, float | None, str | None]:
    """Extract address_id, road_id, and geometry from a geodiff entry.

    Args:
        entry: GeodiffEntry to process

    Returns:
        Tuple of (address_id, road_id, gpkg_geom)
    """
    address_id = None
    road_id = None
    gpkg_geom = None
    plugin_score = None
    plugin_geoconder = None

    for change in entry.changes:
        if change.column == COLUMN_ADDRESS_ID:
            value = change.new or change.old
            address_id = int(value) if value is not None else None
        elif change.column == COLUMN_GEOMETRY:
            value = change.new or change.old
            gpkg_geom = str(value) if value is not None else None
        elif change.column == COLUMN_ROAD_ID:
            value = change.new or change.old
            road_id = int(value) if value is not None else None
        elif change.column == COLUMN_PLUGIN_SCORE:
            value = change.new or change.old
            plugin_score = float(value) if value is not None else None
        elif change.column == COLUMN_PLUGIN_GEOCODER:
            value = change.new or change.old
            plugin_geoconder = str(value) if value is not None else None

    return address_id, road_id, gpkg_geom, plugin_score, plugin_geoconder


def process_entry(
    entry: GeodiffEntry,
    settings: SettingsProtocol,
    cli_runner: CliRunnerProtocol,
    cli_app: Any,
    anncsu_sdk: AnncsuConsultazione,
    geodiff: GeoDiffProtocol,
    wkb_loader: Any,
    logger: LoggerProtocol,
) -> bool:
    """Process a single geodiff entry and call the ANNCSU CLI.

    Args:
        entry: GeodiffEntry to process
        settings: Application settings
        cli_runner: CLI runner instance
        cli_app: ANNCSU CLI app
        anncsu_sdk: AnncsuConsultazione instance for SDK calls with CLI token
        geodiff: GeoDiff instance for geometry conversion
        wkb_loader: shapely.wkb.loads function
        logger: Logger for output
    Returns:
        True if processing succeeded, False otherwise
    """
    action = entry.type
    table = entry.table

    # Extract relevant data from entry changes that have to exist
    address_id, road_id, gpkg_geom, plugin_score, plugin_geoconder = extract_entry_data(entry)
    if address_id is None:
        logger.warn(f"Entry has no address_id; skipping entry: {entry}")
        return False

    # Do nothing if record is the original one without changes due to first insert, to avoid unnecessary CLI calls
    if (plugin_score is not None and plugin_geoconder is not None) and (
        plugin_score == 1.0 and plugin_geoconder == "ANNCSU" and action == "insert"
    ):
        logger.info(f"Entry has no changes (PLUGIN_SCORE=1.0 and PLUGIN_GEOCODER=ANNCSU); skipping entry: {entry}")
        return True

    # Parse geometry if present
    if gpkg_geom:
        try:
            coords = parse_gpkg_to_coordinates(gpkg_geom, geodiff, wkb_loader)
            x, y = coords.x, coords.y
            logger.info(f"Extracted coordinates: x={x}, y={y}")
        except ValueError as e:
            logger.warn(f"Geometry error for address_id={address_id}, road_id={road_id}: {e}")
            return False

        # check if coordinates are valid numbers, if not skip the update to avoid CLI errors
        try:
            x = float(x)
            y = float(y)
        except (TypeError, ValueError):
            logger.warn(
                f"Invalid coordinates to update for address_id={address_id}, road_id={road_id}: x={x}, y={y}; skipping entry"
            )
            return False
    else:
        logger.warn(f"No geometry found for address_id={address_id}, road_id={road_id}; skipping anncsu update")
        return False

    logger.info(f"Preparing ANNCSU CLI call: action={action} table={table} address_id={address_id} road_id={road_id}")

    # a special case of insert when address_id is negative e.g. it is a new record without an assigned address_id, in this case we have to extract the ODONIMO from the scope database using the road_id and use it as address_id for the CLI call
    if action == "insert" and address_id < 0:
        logger.info(f"Address ID is negative ({address_id}), means it is a new record")
        # TODO: do insert when sdk or cli available to create a new record and get the assigned address_id
        logger.warn(f"Insert action with negative address_id is not implemented yet; skipping entry: {entry}")
        return False

    # manage insert/update of coordinates in ANNCSU via CLI calls, based on the geodiff entry type
    if action == "insert" or action == "update":
        logger.info(f"{action} {len(entry.changes)} column values in {table} with PK: address_id={address_id}")

        # check if record exists in ANNCSU before deciding to insert or update
        # get anncsu data basing on address_id
        # response = anncsu_sdk.queryparam.prognazacc_get_query_param(
        #     prognazacc=f"{address_id}",
        # )
        commands = [
            "pa",
            "accesso",
            "--prognazacc",
            str(address_id) if address_id else "",
            "--production",
            "--token-endpoint",
            "https://auth.interop.pagopa.it/token.oauth2",
            "--json",
        ]
        command_string = " ".join(commands)
        logger.debug(f"Invoking ANNCSU CLI with command: {command_string}")

        # run CLI command to query existing record in ANNCSU based on address_id
        response = cli_runner.invoke(
            cli_app,
            commands,
        )
        if response.exit_code != 0:
            logger.error(
                f"Failed to query ANNCSU for address_id={address_id}: {response.output} - exit code {response.exit_code}"
            )
            return False

        json_data = json.loads(response.output)
        if len(json_data) == 0:
            logger.warn(f"No ANNCSU record found for address_id={address_id}; skipping update")
            return False
        if len(json_data) > 1:
            logger.warn(f"Multiple ANNCSU records found for address_id={address_id}; skipping update")
            return False
        anncsu_record = json_data[0]

        # get anncsu coordinate to check if they are been modified
        # if coordinates are the same, skip the update to avoid unnecessary CLI calls
        coord_x = anncsu_record["coordX"]
        coord_y = anncsu_record["coordY"]
        logger.info(
            f"{action} found ANNCSU record for address_id={address_id} with coordinates: coordX={coord_x}, coordY={coord_y}"
        )

        # quota = anncsu_record.quota
        if coord_x and coord_y:
            # check if coordinates are valid numbers
            try:
                coord_x = float(coord_x)
                coord_y = float(coord_y)
            except (TypeError, ValueError):
                logger.warn(
                    f"Invalid original ANNCSU coordinates for address_id={address_id}: coordX={coord_x}, coordY={coord_y}; skipping update"
                )
            else:
                # if valid numbers, check if they are the same of the coordinates to update,
                # if they are the same skip the update to avoid unnecessary CLI calls
                if (
                    abs(x - coord_x) <= settings.coordinate_distance_threshold
                    and abs(y - coord_y) <= settings.coordinate_distance_threshold
                ):
                    logger.info(f"Coordinates for address_id={address_id} are the same in ANNCSU; skipping update")
                    return True

        # update coordinates via CLI
        logger.info(
            f"{action} ANNCSU record for address_id={address_id} with coordinates: coordX={x:.9f}, coordY={y:.9f}"
        )
        commands = [
            "coordinate",
            "update",
            "--production",
            "--codcom",
            settings.codice_comune,
            "--progr-civico",
            str(address_id) if address_id else "",
            "--x",
            f"{x:.9f}",
            "--y",
            f"{y:.9f}",
            "--metodo",
            "4",  # TODO: define a method to determine the update method (e.g., based on entry type or other criteria)
            "--token-endpoint",
            "https://auth.interop.pagopa.it/token.oauth2",
            "--json",
        ]
        command_string = " ".join(commands)
        logger.debug(f"Invoking ANNCSU CLI with command: {command_string}")

        # run CLI command to update coordinates
        result = cli_runner.invoke(
            cli_app,
            commands,
        )
        if result.exit_code != 0:
            logger.error(f"ANNCSU CLI coordinate update failed: {result.output} - exit code {result.exit_code}")
            return False
        logger.info(f"ANNCSU CLI coordinate update succeeded: {result.output}")
        return True

    elif action == "delete":
        logger.info(f"Delete {len(entry.changes)} values from {table}")
        # TODO: implement delete CLI call
        return True

    else:
        logger.warn(f"Unknown action type: {action}")
        return False


def process_all_entries(
    geodiff_file: GeodiffFile,
    settings: SettingsProtocol,
    cli_runner: CliRunnerProtocol,
    cli_app: Any,
    anncsu_sdk: AnncsuConsultazione,
    geodiff: GeoDiffProtocol,
    wkb_loader: Any,
    logger: LoggerProtocol,
) -> list[EntryResult]:
    """Process all entries in a geodiff file.

    Args:
        geodiff_file: Parsed geodiff file
        settings: Application settings
        cli_runner: CLI runner instance
        cli_app: ANNCSU CLI app
        anncsu_sdk: AnncsuConsultazione instance for SDK calls with CLI token
        geodiff: GeoDiff instance
        wkb_loader: shapely.wkb.loads function
        logger: Logger for output
    Returns:
        List of EntryResult objects
    """
    results = []
    for entry in geodiff_file.geodiff:
        success = process_entry(
            entry=entry,
            settings=settings,
            cli_runner=cli_runner,
            cli_app=cli_app,
            anncsu_sdk=anncsu_sdk,
            geodiff=geodiff,
            wkb_loader=wkb_loader,
            logger=logger,
        )
        results.append(EntryResult(entry_type=entry.type, success=success))
    return results


# ============================================================================
# Geodiff report loading
# ============================================================================


def load_geodiff_report(geodiff_report: str, logger: LoggerProtocol) -> GeodiffFile | None:
    """Load a geodiff report from file path or JSON text.
    Geodiff report can be:
        A) a JSON file generated by geodiff library
        B) a JSON file generated by geodiff-action that has an header with summary and has_changes fields and the actual geodiff report in the changes field
        C) a JSON text directly passed as input

    Args:
        geodiff_report: File path or JSON text
        logger: Logger for output

    Returns:
        Parsed GeodiffFile or None if loading failed
    """
    # Try as file path first
    try:
        report_path = Path(geodiff_report)
        if report_path.exists():
            logger.info(f"Found geodiff report file: {report_path}")
            return GeodiffFile.from_path(report_path)
    except Exception as exc:
        logger.debug(f"Not a valid file path: {exc}")

    # try if it is a geodiff-action report that has an header
    # to be removed if have to be parsed by the geodiff library
    try:
        report_path = Path(geodiff_report)
        if report_path.exists():
            logger.info(f"Check if geodiff-action report file: {report_path}")
            with report_path.open() as f:
                json_data = json.load(f)
            if "has_changes" in json_data and "summary" in json_data:
                logger.info(f"Geodiff-action report file detected: {report_path}")

                # strip the header and load the report as json
                geodiff_json = json_data.get("changes")

                # dump into a string to be parsed by the geodiff library
                geodiff_json_str = json.dumps(geodiff_json)
                return GeodiffFile.from_json_text(geodiff_json_str)
    except Exception as exc:
        logger.debug(f"Not a valid geodiff-action report file: {exc}")

    # Fall back to parsing as JSON text
    logger.info("Attempting to parse geodiff_report as JSON text")
    try:
        return GeodiffFile.from_json_text(geodiff_report)
    except Exception as exc:
        logger.error(f"Failed to parse geodiff_report: {exc}")
        return None


# ============================================================================
# Geodiff schema loading
# ============================================================================


def load_geodiff_schema(geodiff_schema: str, logger: LoggerProtocol) -> bool:
    """Set the COLUMN_* index globals from a geodiff schema.

    The schema is a JSON list of {"name": <column name>, "column": <index>}
    objects. Each COLUMN_* global is looked up by its COLUMN_NAME_* value;
    columns not present in the schema keep their default index.

    Args:
        geodiff_schema: File path or JSON text of the geodiff schema
        logger: Logger for output

    Returns:
        True if the schema was loaded, False otherwise
    """
    global COLUMN_ADDRESS_ID, COLUMN_GEOMETRY, COLUMN_ROAD_ID
    global COLUMN_PLUGIN_SCORE, COLUMN_PLUGIN_GEOCODER

    # Try as file path first, then fall back to JSON text
    try:
        schema_path = Path(geodiff_schema)
        if schema_path.exists():
            logger.info(f"Found geodiff schema file: {schema_path}")
            schema_text = schema_path.read_text()
        else:
            schema_text = geodiff_schema
    except Exception as exc:
        logger.debug(f"Not a valid file path: {exc}")
        schema_text = geodiff_schema

    try:
        schema = json.loads(schema_text)
        name_to_index = {item["name"]: int(item["column"]) for item in schema}
    except Exception as exc:
        logger.error(f"Failed to parse geodiff_schema: {exc}")
        return False

    def lookup(name: str, default: int) -> int:
        if name not in name_to_index:
            logger.warn(f"Column '{name}' not found in geodiff schema; using default index {default}")
            return default
        return name_to_index[name]

    COLUMN_ADDRESS_ID = lookup(COLUMN_NAME_ADDRESS_ID, COLUMN_ADDRESS_ID)
    COLUMN_GEOMETRY = lookup(COLUMN_NAME_GEOMETRY, COLUMN_GEOMETRY)
    COLUMN_ROAD_ID = lookup(COLUMN_NAME_ROAD_ID, COLUMN_ROAD_ID)
    COLUMN_PLUGIN_SCORE = lookup(COLUMN_NAME_PLUGIN_SCORE, COLUMN_PLUGIN_SCORE)
    COLUMN_PLUGIN_GEOCODER = lookup(COLUMN_NAME_PLUGIN_GEOCODER, COLUMN_PLUGIN_GEOCODER)

    logger.info(
        f"Column indices: address_id={COLUMN_ADDRESS_ID}, geometry={COLUMN_GEOMETRY}, "
        f"road_id={COLUMN_ROAD_ID}, plugin_score={COLUMN_PLUGIN_SCORE}, "
        f"plugin_geocoder={COLUMN_PLUGIN_GEOCODER}"
    )
    return True


# ============================================================================
# CLI Authentication
# ============================================================================


def authenticate_cli(
    cli_runner: CliRunnerProtocol,
    cli_app: Any,
    api_type: str,
    logger: LoggerProtocol,
) -> bool:
    """Authenticate with the ANNCSU CLI.

    Args:
        cli_runner: CLI runner instance
        cli_app: ANNCSU CLI app
        api_type: API type for authentication (e.g., "pa")
        logger: Logger for output

    Returns:
        True if authentication succeeded, False otherwise
    """
    logger.info("Authenticating with ANNCSU CLI...")
    try:
        result = cli_runner.invoke(
            cli_app,
            [
                "auth",
                "login",
                "--api",
                api_type,
                "--token-endpoint",
                "https://auth.interop.pagopa.it/token.oauth2",
            ],
        )
        if result.exit_code != 0:
            logger.error(f"CLI authentication failed: {result.output}")
            return False
        return True
    except Exception as exc:
        logger.error(f"Failed to authenticate with ANNCSU CLI: {exc}")
        return False


# ============================================================================
# Main function
# ============================================================================


def run_action(
    geodiff_report: str,
    geodiff_schema: str,
    settings: SettingsProtocol,
    cli_runner: CliRunnerProtocol,
    cli_app: Any,
    geodiff: GeoDiffProtocol,
    wkb_loader: Any,
    logger: LoggerProtocol,
    token: str,
    api_type: str = "pa",
    dry_run: bool = False,
) -> bool:
    """Run the ANNCSU update action.

    This is the main entry point for the action, designed for testability
    via dependency injection.

    Args:
        geodiff_report: File path or JSON text of the geodiff report
        geodiff_schema: File path or JSON text of the geodiff schema
        settings: Application settings
        cli_runner: CLI runner instance
        cli_app: ANNCSU CLI app
        geodiff: GeoDiff instance
        wkb_loader: shapely.wkb.loads function
        logger: Logger for output
        api_type: API type for CLI authentication
        token: Token for SDK calls (if needed)
        dry_run: If True, skip authentication, mock the SDK and log CLI commands
            instead of executing them

    Returns:
        True if action completed successfully, False otherwise
    """
    logger.info("Update ANNCSU DB from geodiff report...")
    logger.info(f"Using codice_comune: \033[36;1m{settings.codice_comune}\033[0m")

    # Set column indices from geodiff schema
    if not load_geodiff_schema(geodiff_schema, logger):
        logger.error("Could not load geodiff schema; aborting")
        return False

    # Load geodiff report
    geodiff_obj = load_geodiff_report(geodiff_report, logger)
    if geodiff_obj is None:
        logger.error("Could not load or validate geodiff report; aborting")
        return False

    if dry_run:
        logger.warn("[DRY RUN] enabled: skipping authentication, ANNCSU CLI calls are only logged")
        cli_runner = DryRunCliRunner(logger)
        sdk = MagicMock(spec=AnncsuConsultazione)
    else:
        # Authenticate with CLI
        if not authenticate_cli(cli_runner, cli_app, api_type, logger):
            logger.error("Failed to authenticate with ANNCSU CLI")
            return False

        # security class to use SDK calls with the same token as CLI
        anncsu_security = Security(bearer=token, validate_expiration=True)
        sdk = AnncsuConsultazione(security=anncsu_security)

    # Process all entries
    logger.info("ANNCSU CLI update based on geodiff report JSON...")
    results = process_all_entries(
        geodiff_file=geodiff_obj,
        settings=settings,
        cli_runner=cli_runner,
        cli_app=cli_app,
        anncsu_sdk=sdk,
        geodiff=geodiff,
        wkb_loader=wkb_loader,
        logger=logger,
    )

    success = all(r.success for r in results)
    if not success:
        logger.warn("One or more ANNCSU CLI calls failed (see logs)")

    logger.info("Anncsu Update Action ended")
    return success


# ============================================================================
# Module-level execution (for GitHub Action)
# ============================================================================


def main() -> None:
    """Main entry point when running as a GitHub Action."""
    # Import dependencies only when running as main
    from typer.testing import CliRunner
    from shapely import wkb
    from pygeodiff import GeoDiff

    from actions import context, core
    import functions
    from settings import AnncsuUpdateSettings
    from anncsu.cli import app

    # Log startup
    version: str = core.get_version()
    core.info(f"Starting Anncsu Update Action - \033[32;1m{version}")

    # Get inputs
    geodiff_report: str = core.get_input("geodiff_report", True)
    geodiff_schema: str = core.get_input("geodiff_schema", True)
    core.info(f"geodiff_report: \033[36;1m{geodiff_report}")
    core.info(f"geodiff_schema: \033[36;1m{geodiff_schema}")
    _token: str = core.get_input("token", True)  # noqa: F841

    # Debug info
    with core.group("uv"):
        functions.check_output("uv -V", False)
        functions.check_output("uv python dir", False)

    ctx = {k: v for k, v in vars(context).items() if not k.startswith("__")}
    del ctx["os"]
    with core.group("GitHub Context Data"):
        core.debug(json.dumps(ctx, indent=4))

    # Load settings
    core.info("Loading Anncsu Update Settings...")
    try:
        settings = AnncsuUpdateSettings()
        core.debug(f"Loaded settings: {settings.model_dump_json()}")
    except Exception as exc:
        core.error(f"Failed to load Anncsu Update Settings: {exc}")
        raise SystemExit(1) from exc
        # core.set_failed(f"Failed to load Anncsu Update Settings: {exc}")

    # Create CLI runner
    cli_runner = CliRunner()

    # Run the action
    success = run_action(
        geodiff_report=geodiff_report,
        geodiff_schema=geodiff_schema,
        settings=settings,
        cli_runner=cli_runner,
        cli_app=app,
        geodiff=GeoDiff(),
        wkb_loader=wkb.loads,
        logger=core,
        token=_token,
        api_type="pa",
        dry_run=settings.dry_run,
    )

    if success:
        print("\033[32;1mAnncsu Update Action completed successfully\033[0m")
    else:
        core.error("\033[31;1mAnncsu Update Action failed. Check logs for details.\033[0m")
        raise SystemExit(1)


# Only execute when running directly, not when importing
if __name__ == "__main__":
    main()
