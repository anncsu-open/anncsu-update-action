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

from geodiff_models import GeodiffEntry, GeodiffEntryDict, GeodiffFile, GeodiffSchema

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
    def group(self, name: str, /) -> Any: ...
    def get_input(self, name: str, required: bool = False, /) -> str: ...


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

    def create_wkb_from_gpkg_header(self, data: bytes, /) -> list[bytes]: ...


@runtime_checkable
class GeometryProtocol(Protocol):
    """Protocol for geometry objects."""

    is_valid: bool
    geom_type: str
    coords: Any


# ============================================================================
# Column names of geodiff entries
# ============================================================================

# ANNCSU interop authentication endpoint used by all CLI calls (a public URL, not a secret)
TOKEN_ENDPOINT = "https://auth.interop.pagopa.it/token.oauth2"  # nosec B105

# column names used to look up the entry values through the geodiff schema
COLUMN_NAME_ADDRESS_ID = "PROGRESSIVO_ACCESSO"
COLUMN_NAME_GEOMETRY = "geom"
COLUMN_NAME_ROAD_ID = "PROGRESSIVO_NAZIONALE"
COLUMN_NAME_ODONIMO = "ODONIMO"
COLUMN_NAME_PLUGIN_SCORE = "PLUGIN_SCORE"
COLUMN_NAME_PLUGIN_GEOCODER = "PLUGIN_GEOCODER"
COLUMN_NAME_PLUGIN_SEZIONI_CENSIMENTO = "PLUGIN_SEZIONI_CENSIMENTO"
COLUMN_NAME_CODICE_COMUNE = "CODICE_COMUNE"
COLUMN_NAME_CIVICO = "CIVICO"
COLUMN_NAME_METRICO = "METRICO"
COLUMN_NAME_ESPONENTE = "ESPONENTE"
COLUMN_NAME_SPECIFICITA = "SPECIFICITA"
COLUMN_NAME_CODICE_COMUNALE_ACCESSO = "CODICE_COMUNALE_ACCESSO"
COLUMN_NAME_QUOTA = "QUOTA"
COLUMN_NAME_METODO = "METODO"
COLUMN_NAMES = (
    COLUMN_NAME_ADDRESS_ID,
    COLUMN_NAME_GEOMETRY,
    COLUMN_NAME_ROAD_ID,
    COLUMN_NAME_ODONIMO,
    COLUMN_NAME_PLUGIN_SCORE,
    COLUMN_NAME_PLUGIN_GEOCODER,
    COLUMN_NAME_PLUGIN_SEZIONI_CENSIMENTO,
    COLUMN_NAME_CODICE_COMUNE,
    COLUMN_NAME_CIVICO,
    COLUMN_NAME_METRICO,
    COLUMN_NAME_ESPONENTE,
    COLUMN_NAME_SPECIFICITA,
    COLUMN_NAME_CODICE_COMUNALE_ACCESSO,
    COLUMN_NAME_QUOTA,
    COLUMN_NAME_METODO,
)

# default metodo di rilevazione used when the entry has no METODO value
DEFAULT_METODO = "4"


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
    coordinate update command is always reached and logged. The "pa odonimo"
    query returns a fake road named as the searched one.
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
        elif args[:2] == ["pa", "odonimo"]:
            denom = args[args.index("--denom") + 1] if "--denom" in args else ""
            denomuff = base64.b64decode(denom).decode("utf-8") if denom else ""
            output = json.dumps([{"prognaz": "0", "dug": None, "denomuff": denomuff}])
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


def extract_entry_data(
    entry_dict: GeodiffEntryDict,
) -> tuple[int | None, int | None, str | None, float | None, str | None]:
    """Extract address_id, road_id, geometry and plugin values from a geodiff entry.

    Args:
        entry_dict: Geodiff entry changes keyed by column name

    Returns:
        Tuple of (address_id, road_id, gpkg_geom, plugin_score, plugin_geocoder)
    """
    address_id = entry_dict.value(COLUMN_NAME_ADDRESS_ID)
    road_id = entry_dict.value(COLUMN_NAME_ROAD_ID)
    gpkg_geom = entry_dict.value(COLUMN_NAME_GEOMETRY)
    plugin_score = entry_dict.value(COLUMN_NAME_PLUGIN_SCORE)
    plugin_geocoder = entry_dict.value(COLUMN_NAME_PLUGIN_GEOCODER)
    plugin_sezioni_censimento = entry_dict.value(COLUMN_NAME_PLUGIN_SEZIONI_CENSIMENTO)

    return (
        int(address_id) if address_id is not None else None,
        int(road_id) if road_id is not None else None,
        str(gpkg_geom) if gpkg_geom is not None else None,
        float(plugin_score) if plugin_score is not None else None,
        str(plugin_geocoder) if plugin_geocoder is not None else None,
        str(plugin_sezioni_censimento) if plugin_sezioni_censimento is not None else None,
    )


def extract_odonimo(entry_dict: GeodiffEntryDict) -> str | None:
    """Extract the road name (ODONIMO) from a geodiff entry.

    Args:
        entry_dict: Geodiff entry changes keyed by column name

    Returns:
        The road name, or None if the entry has no ODONIMO value
    """
    odonimo = entry_dict.value(COLUMN_NAME_ODONIMO)
    return str(odonimo) if odonimo is not None else None


def cli_value(entry_dict: GeodiffEntryDict, name: str) -> str | None:
    """Return a column value of a geodiff entry formatted as a CLI argument.

    Integral floats are rendered without decimals (12.0 -> "12") and empty
    strings are treated as missing.

    Args:
        entry_dict: Geodiff entry changes keyed by column name
        name: Column name

    Returns:
        The value as a string, or None if missing or empty
    """
    value = entry_dict.value(name)
    if value is None:
        return None
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    text = str(value).strip()
    return text or None


# ============================================================================
# ANNCSU CLI operations
# ============================================================================


def query_anncsu_record(
    address_id: int,
    cli_runner: CliRunnerProtocol,
    cli_app: Any,
    logger: LoggerProtocol,
) -> dict[str, Any] | None:
    """Query ANNCSU for the single access record identified by address_id.

    Args:
        address_id: ANNCSU progressivo accesso (prognazacc)
        cli_runner: CLI runner instance
        cli_app: ANNCSU CLI app
        logger: Logger for output

    Returns:
        The ANNCSU record, or None if the query failed or did not return exactly one record
    """
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
        TOKEN_ENDPOINT,
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
        return None

    json_data = json.loads(response.output)
    if len(json_data) == 0:
        logger.warn(f"No ANNCSU record found for address_id={address_id}; skipping update")
        return None
    if len(json_data) > 1:
        logger.warn(f"Multiple ANNCSU records found for address_id={address_id}; skipping update")
        return None
    return json_data[0]


def query_anncsu_road(
    odonimo: str | None,
    codice_comune: str,
    cli_runner: CliRunnerProtocol,
    cli_app: Any,
    logger: LoggerProtocol,
) -> dict[str, Any] | None:
    """Query ANNCSU for the road (odonimo) matching a road name in a municipality.

    The ANNCSU search is a partial match on the name, so when more than one
    road is returned the one whose name matches exactly (case insensitive,
    with or without the DUG e.g. "VIA") is selected.

    Args:
        odonimo: Road name to look for (e.g. "VIA ROMA")
        codice_comune: Codice Belfiore of the municipality
        cli_runner: CLI runner instance
        cli_app: ANNCSU CLI app
        logger: Logger for output

    Returns:
        The ANNCSU road record (with "prognaz", "dug", "denomuff", ...), or None
        if the query failed or no single road matches
    """
    odonimo = odonimo.strip() if odonimo else ""
    if not odonimo:
        logger.warn("Empty odonimo; skipping ANNCSU road query")
        return None

    # the CLI expects the (partial) road name base64 encoded
    denom = base64.b64encode(odonimo.encode("utf-8")).decode("ascii")
    commands = [
        "pa",
        "odonimo",
        "--codcom",
        codice_comune,
        "--denom",
        denom,
        "--production",
        "--token-endpoint",
        TOKEN_ENDPOINT,
        "--json",
    ]
    command_string = " ".join(commands)
    logger.debug(f"Invoking ANNCSU CLI with command: {command_string}")

    # run CLI command to search the road in ANNCSU based on its name
    # NOTE: the CLI exits with code 1 also when no road is found
    response = cli_runner.invoke(
        cli_app,
        commands,
    )
    if response.exit_code != 0:
        logger.warn(
            f"No ANNCSU road found for odonimo={odonimo!r} in codcom={codice_comune}: {response.output} - exit code {response.exit_code}"
        )
        return None

    try:
        json_data = json.loads(response.output)
    except json.JSONDecodeError as exc:
        logger.error(f"Invalid ANNCSU road query output for odonimo={odonimo!r}: {exc}")
        return None
    if len(json_data) == 0:
        logger.warn(f"No ANNCSU road found for odonimo={odonimo!r} in codcom={codice_comune}")
        return None
    if len(json_data) == 1:
        return json_data[0]

    # multiple partial matches: keep the exact ones
    wanted = odonimo.casefold()
    exact = [
        road
        for road in json_data
        if wanted
        in {
            (road.get("denomuff") or "").strip().casefold(),
            f"{road.get('dug') or ''} {road.get('denomuff') or ''}".strip().casefold(),
        }
    ]
    if len(exact) == 1:
        return exact[0]
    logger.warn(
        f"{len(json_data)} ANNCSU roads found for odonimo={odonimo!r} in codcom={codice_comune} "
        f"({len(exact)} exact matches); skipping"
    )
    return None


def update_coordinates(
    entry_dict: GeodiffEntryDict,
    address_id: int,
    x: float,
    y: float,
    settings: SettingsProtocol,
    cli_runner: CliRunnerProtocol,
    cli_app: Any,
    logger: LoggerProtocol,
) -> bool:
    """Update the coordinates of an existing ANNCSU access via CLI.

    The update is skipped if the ANNCSU coordinates are already within
    settings.coordinate_distance_threshold of the new ones.

    Args:
        entry_dict: Geodiff entry being processed, with its changes keyed by column name
        address_id: ANNCSU progressivo accesso
        x: New X coordinate
        y: New Y coordinate
        settings: Application settings
        cli_runner: CLI runner instance
        cli_app: ANNCSU CLI app
        logger: Logger for output

    Returns:
        True if the update succeeded or was not needed, False otherwise
    """
    action = entry_dict.type
    logger.info(
        f"{action} {len(entry_dict.changes)} column values in {entry_dict.table} with PK: address_id={address_id}"
    )

    # check if record exists in ANNCSU before updating
    anncsu_record = query_anncsu_record(address_id, cli_runner, cli_app, logger)
    if anncsu_record is None:
        return False

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
    logger.info(f"{action} ANNCSU record for address_id={address_id} with coordinates: coordX={x:.9f}, coordY={y:.9f}")
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
        TOKEN_ENDPOINT,
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


def insert_address(
    entry_dict: GeodiffEntryDict,
    address_id: int,
    x: float,
    y: float,
    settings: SettingsProtocol,
    cli_runner: CliRunnerProtocol,
    cli_app: Any,
    logger: LoggerProtocol,
) -> bool:
    """Insert a new ANNCSU access via CLI.

    A negative address_id marks a record that does not exist yet in ANNCSU
    and is not handled yet. Otherwise the road (ODONIMO) is looked up in
    ANNCSU and the accesso is inserted with "accesso insert", taking the
    codice comune, progressivo nazionale and civico data from the entry.

    Args:
        entry_dict: Changes of the entry keyed by column name
        address_id: ANNCSU progressivo accesso (negative for new records)
        x: X coordinate
        y: Y coordinate
        settings: Application settings
        cli_runner: CLI runner instance
        cli_app: ANNCSU CLI app
        logger: Logger for output

    Returns:
        True if the insert succeeded, False otherwise
    """
    # a special case of insert when address_id is negative e.g. it is a new record without an assigned address_id, in this case we have to extract the ODONIMO from the scope database using the road_id and use it as address_id for the CLI call
    if address_id < 0:
        logger.info(f"Address ID is negative ({address_id}), means it is a new record")
    else:
        logger.warn(f"Address ID is positive ({address_id}), means it is an existing record should be an update")
        return False

    # need to check that the address exists in ANNCSU before attempting to insert
    # address is looked by name
    odonimo = extract_odonimo(entry_dict)
    logger.info(f"Checking if road exists in ANNCSU for odonimo={odonimo!r}")
    road = query_anncsu_road(odonimo, settings.codice_comune, cli_runner, cli_app, logger)
    if road is None:
        logger.warn(f"Road odonimo={odonimo!r} not found in ANNCSU; skipping insert for address_id={address_id}")
        return False
    logger.debug(f"Queried ANNCSU road: {road}")
    logger.info(f"Found ANNCSU road prognaz={road.get('prognaz')} for odonimo={odonimo!r}")

    # do insert basing on the found ANNCSU road and the provided entry data
    codcom = cli_value(entry_dict, COLUMN_NAME_CODICE_COMUNE) or settings.codice_comune
    prognaz = str(road["prognaz"]) if road.get("prognaz") else None
    if prognaz is None:
        logger.warn(f"No progressivo nazionale for odonimo={odonimo!r}; skipping insert for address_id={address_id}")
        return False

    # exactly one of numero or metrico is required
    numero = cli_value(entry_dict, COLUMN_NAME_CIVICO)
    metrico = cli_value(entry_dict, COLUMN_NAME_METRICO)
    if (numero is None) == (metrico is None):
        logger.warn(
            f"Exactly one of {COLUMN_NAME_CIVICO}={numero!r} or {COLUMN_NAME_METRICO}={metrico!r} is required; "
            f"skipping insert for address_id={address_id}"
        )
        return False

    # only numero or metric are allowed, not both
    if numero is not None and metrico is not None:
        logger.warn(
            f"Both {COLUMN_NAME_CIVICO}={numero!r} and {COLUMN_NAME_METRICO}={metrico!r} are provided; "
            f"skipping insert for address_id={address_id}"
        )
        return False

    # get sezione censimento from the entry dict
    sezione_censimento = cli_value(entry_dict, COLUMN_NAME_PLUGIN_SEZIONI_CENSIMENTO)
    if sezione_censimento is None:
        logger.warn(f"No sezione censimento provided; Inserting fake value '9999' for address_id={address_id}")
        sezione_censimento = "9999"

    # prepare command
    commands = [
        "accesso",
        "insert",
        "--production",
        "--codcom",
        codcom,
        "--prognaz",
        prognaz,
        "--sezione-censimento",
        sezione_censimento,
    ]
    optional_args = [
        ("--numero", numero),
        ("--metrico", metrico),
        ("--esponente", cli_value(entry_dict, COLUMN_NAME_ESPONENTE)),
        ("--specificita", cli_value(entry_dict, COLUMN_NAME_SPECIFICITA)),
        ("--codice-civico-comunale", cli_value(entry_dict, COLUMN_NAME_CODICE_COMUNALE_ACCESSO)),
        ("--coord-x", f"{x:.9f}"),
        ("--coord-y", f"{y:.9f}"),
        ("--coord-z", cli_value(entry_dict, COLUMN_NAME_QUOTA)),
        ("--metodo", cli_value(entry_dict, COLUMN_NAME_METODO) or DEFAULT_METODO),
    ]
    for option, value in optional_args:
        if value is not None:
            commands.extend([option, value])
    commands.extend(["--token-endpoint", TOKEN_ENDPOINT, "--json"])

    command_string = " ".join(commands)
    logger.debug(f"Invoking ANNCSU CLI with command: {command_string}")

    # in dry run mode (ANNCSU_UPDATE_DRY_RUN) only log the insert without executing it
    if settings.dry_run:
        logger.info(f"[DRY RUN] would insert ANNCSU accesso for address_id={address_id}: {command_string}")
        return True

    # run CLI command to insert the new accesso
    result = cli_runner.invoke(
        cli_app,
        commands,
    )
    if result.exit_code != 0:
        logger.error(f"ANNCSU CLI accesso insert failed: {result.output} - exit code {result.exit_code}")
        return False
    logger.info(f"ANNCSU CLI accesso insert succeeded: {result.output}")
    return True


def delete_address(
    entry_dict: GeodiffEntryDict,
    address_id: int,
    settings: SettingsProtocol,
    cli_runner: CliRunnerProtocol,
    cli_app: Any,
    logger: LoggerProtocol,
) -> bool:
    """Delete an ANNCSU access via CLI.

    Args:
        entry_dict: Geodiff entry being processed, with its changes keyed by column name
        address_id: ANNCSU progressivo accesso
        settings: Application settings
        cli_runner: CLI runner instance
        cli_app: ANNCSU CLI app
        logger: Logger for output

    Returns:
        True if the delete succeeded, False otherwise
    """
    logger.info(f"Delete {len(entry_dict.changes)} values from {entry_dict.table} with PK: address_id={address_id}")
    # TODO: delete when sdk or cli available to delete an existing record
    logger.warn(f"!!! Delete action is not implemented yet; skipping entry: {entry_dict} !!!")
    return False


def process_entry(
    entry: GeodiffEntry,
    schema: GeodiffSchema,
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
        schema: Geodiff schema mapping column names to column indices
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

    # map the entry changes to column names (also validates the entry type)
    try:
        entry_dict = GeodiffEntryDict.from_entry(entry, schema)
    except ValueError as exc:
        logger.error(f"Invalid geodiff entry: {exc}; skipping entry: {entry}")
        return False

    # Extract relevant data from entry changes that have to exist
    address_id, road_id, gpkg_geom, plugin_score, plugin_geocoder, plugin_sezioni_censimento = extract_entry_data(entry_dict)
    if address_id is None:
        logger.warn(f"Entry has no address_id; skipping entry: {entry}")
        return False

    # Do nothing if record is the original one without changes due to first insert, to avoid unnecessary CLI calls
    if (plugin_score is not None and plugin_geocoder is not None) and (
        plugin_score == 1.0 and plugin_geocoder == "ANNCSU" and action == "insert"
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

    if action == "insert":
        return insert_address(entry_dict, address_id, x, y, settings, cli_runner, cli_app, logger)
    elif action == "update":
        # manage a special case for plugin_sezioni_censimento to
        # do insert instead of update because sezioni_censimento has been added later
        if (plugin_sezioni_censimento is not None) \
           and (address_id < 0) \
           and (road_id is not None and road_id < 0):
            return insert_address(entry_dict, address_id, x, y, settings, cli_runner, cli_app, logger)

        return update_coordinates(entry_dict, address_id, x, y, settings, cli_runner, cli_app, logger)
    elif action == "delete":
        return delete_address(entry_dict, address_id, settings, cli_runner, cli_app, logger)
    else:
        logger.warn(f"Unknown action type: {action}")
        return False


def process_all_entries(
    geodiff_file: GeodiffFile,
    schema: GeodiffSchema,
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
        schema: Geodiff schema mapping column names to column indices
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
            schema=schema,
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


def load_geodiff_schema(geodiff_schema: str, logger: LoggerProtocol) -> GeodiffSchema | None:
    """Load a geodiff schema.

    The schema is a JSON list of {"name": <column name>, "column": <index>}
    objects. A warning is logged for each COLUMN_NAME_* column used by the
    action that is not present in the schema.

    Args:
        geodiff_schema: File path or JSON text of the geodiff schema
        logger: Logger for output

    Returns:
        The parsed schema, or None if it could not be loaded
    """

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
        return None

    for name in COLUMN_NAMES:
        if name not in name_to_index:
            logger.warn(f"Column '{name}' not found in geodiff schema; its value will be missing from every entry")

    logger.info(
        "Column indices: "
        + ", ".join(f"{name}={name_to_index[name]}" for name in COLUMN_NAMES if name in name_to_index)
    )
    return schema


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
                TOKEN_ENDPOINT,
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

    # Load geodiff schema to map entry columns to names
    schema = load_geodiff_schema(geodiff_schema, logger)
    if schema is None:
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
        schema=schema,
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
