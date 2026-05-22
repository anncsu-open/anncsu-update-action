"""Pytest fixtures for tests."""

import sys
import json
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from contextlib import contextmanager
from typing import Any

import pytest

# Make the package source importable from tests
sys.path.insert(0, "src")


# ============================================================================
# Mock Classes for Dependency Injection
# ============================================================================


@dataclass
class MockLogger:
    """Mock logger that captures all log messages."""

    messages: list[tuple[str, str]] = field(default_factory=list)
    failed_message: str | None = None
    version: str = "1.0.0-test"

    def get_version(self) -> str:
        return self.version

    def info(self, message: str) -> None:
        self.messages.append(("info", message))

    def debug(self, message: str) -> None:
        self.messages.append(("debug", message))

    def warn(self, message: str) -> None:
        self.messages.append(("warn", message))

    def error(self, message: str) -> None:
        self.messages.append(("error", message))

    def set_failed(self, message: str) -> None:
        self.failed_message = message

    def group(self, name: str) -> Any:
        @contextmanager
        def _cm():
            yield None

        return _cm()

    def get_input(self, name: str, required: bool = False) -> str:
        return ""


@dataclass
class MockSettings:
    """Mock settings object."""

    codice_comune: str = "I501"
    coordinate_distance_threshold: float = 0.001
    geocoded_table: str = "geocoded_civici"

    def model_dump_json(self) -> str:
        return json.dumps(
            {
                "ANNCSU_UPDATE_CODICE_COMUNE": self.codice_comune,
                "coordinate_distance_threshold": self.coordinate_distance_threshold,
            }
        )


@dataclass
class MockCliResult:
    """Mock CLI invocation result."""

    exit_code: int = 0
    output: str = "OK"


@dataclass
class MockCliRunner:
    """Mock CLI runner that captures invocations.

    Auto-detects ANNCSU query calls (args containing "accesso") and returns
    query_result for those when set, otherwise falls back to result.
    results_sequence overrides all auto-detection when provided.
    """

    invocations: list[tuple[Any, list[str]]] = field(default_factory=list)
    result: MockCliResult = field(default_factory=MockCliResult)
    results_sequence: list[MockCliResult] = field(default_factory=list)
    _call_count: int = 0
    query_result: "MockCliResult | None" = None

    def invoke(self, app: Any, args: list[str]) -> MockCliResult:
        self.invocations.append((app, args))
        if self.results_sequence:
            result = self.results_sequence[self._call_count % len(self.results_sequence)]
            self._call_count += 1
            return result
        if self.query_result is not None and "accesso" in args:
            return self.query_result
        return self.result


@dataclass
class MockGeoDiff:
    """Mock GeoDiff for geometry conversion."""

    wkb_result: bytes = b"FAKE-WKB"
    should_raise: bool = False

    def create_wkb_from_gpkg_header(self, data: bytes) -> list[bytes]:
        if self.should_raise:
            raise ValueError("Mock GeoDiff error")
        return [self.wkb_result]


@dataclass
class MockGeometry:
    """Mock shapely geometry object."""

    is_valid: bool = True
    geom_type: str = "Point"
    _coords: list[tuple[float, float]] = field(default_factory=lambda: [(12.34, 56.78)])

    @property
    def coords(self) -> list[tuple[float, float]]:
        return self._coords


@dataclass
class MockPoint:
    """Mock shapely Point class."""

    x: float = 0.0
    y: float = 0.0

    def __init__(self, coord: tuple[float, float]):
        self.x = coord[0]
        self.y = coord[1]


@dataclass
class MockAnncsuRecord:
    """Mock ANNCSU record returned by SDK."""

    coord_x: float | None = 10.0  # Different from mock_wkb_loader (12.34)
    coord_y: float | None = 50.0  # Different from mock_wkb_loader (56.78)
    dug: str = "R1AAAQAAAAABAQAAAAAAAICcwitAAAAAwInzREA="


@dataclass
class MockAnncsuResponse:
    """Mock ANNCSU SDK response."""

    res: str = "OK"
    message: str = ""
    data: list[MockAnncsuRecord] = field(default_factory=lambda: [MockAnncsuRecord()])


@dataclass
class MockPathParam:
    """Mock ANNCSU SDK pathparam."""

    response: MockAnncsuResponse = field(default_factory=MockAnncsuResponse)

    def prognazarea_get_path_param(self, prognaz: str) -> MockAnncsuResponse:
        return self.response


@dataclass
class MockAnncsuConsultazione:
    """Mock ANNCSU SDK consultazione class."""

    pathparam: MockPathParam = field(default_factory=MockPathParam)

    def __init__(self, security: Any = None):
        self.pathparam = MockPathParam()


@dataclass
class MockSecurity:
    """Mock ANNCSU Security class."""

    bearer: str = "test-token"
    validate_expiration: bool = True


# ============================================================================
# Fixtures - Mocks
# ============================================================================


@pytest.fixture
def mock_logger() -> MockLogger:
    """Create a fresh mock logger."""
    return MockLogger()


@pytest.fixture
def mock_settings() -> MockSettings:
    """Create mock settings."""
    return MockSettings()


@pytest.fixture
def mock_cli_runner() -> MockCliRunner:
    """Create a mock CLI runner with auto-detection for ANNCSU query calls.

    - "pa accesso" calls return JSON with different coords (to trigger updates)
    - all other calls (auth, coordinate update) return exit_code=0 with "OK"
    """
    return MockCliRunner(
        query_result=MockCliResult(exit_code=0, output='[{"coordX": 10.0, "coordY": 50.0}]'),
    )


@pytest.fixture
def mock_geodiff() -> MockGeoDiff:
    """Create a mock GeoDiff."""
    return MockGeoDiff()


@pytest.fixture
def mock_wkb_loader():
    """Create a mock WKB loader function."""

    def _loader(data: bytes) -> MockGeometry:
        return MockGeometry()

    return _loader


@pytest.fixture
def mock_point_class():
    """Return the MockPoint class."""
    return MockPoint


@pytest.fixture
def mock_cli_app():
    """Mock CLI app object."""
    return SimpleNamespace(name="mock-anncsu-cli")


@pytest.fixture
def mock_anncsu_security() -> MockSecurity:
    """Create a mock ANNCSU Security object."""
    return MockSecurity()


@pytest.fixture
def mock_anncsu_consultazione() -> MockAnncsuConsultazione:
    """Create a mock ANNCSU Consultazione SDK."""
    return MockAnncsuConsultazione()


# ============================================================================
# Fixtures - Environment
# ============================================================================


@pytest.fixture
def mock_env_file(tmp_path: Path) -> Path:
    """Create a mock .env file with test credentials."""
    env_content = """
ANNCSU_UPDATE_CODICE_COMUNE=I501
"""
    env_file = tmp_path / ".env"
    env_file.write_text(env_content.strip())
    return env_file


# ============================================================================
# Fixtures - Geodiff JSON Data
# ============================================================================


@pytest.fixture
def geodiff_update_json():
    return json.dumps(
        {
            "geodiff": [
                {
                    "table": "simple",
                    "type": "update",
                    "changes": [
                        {"column": 0, "old": 2},
                        {
                            "column": 1,
                            "old": "R1AAAeYQAAABAQAAAPBDGq/kSde/+HS2Feb94T8=",
                            "new": "R1AAAeYQAAABAQAAAMp+uos0te2/hISLbYZyzj8=",
                        },
                        {"column": 3, "old": 2, "new": 9999},
                    ],
                }
            ]
        }
    )


@pytest.fixture
def geodiff_real_value_update_json():
    """Geodiff update without geometry change (only value change)."""
    # NOTE: PK are
    # columns: 0: address_id (AKA PROGRESSIVO_ACCESSO)
    # columns: 2: road_id (AKA PROGRESSIVO_NAZIONALE)
    return json.dumps(
        {
            "geodiff": [
                {
                    "changes": [
                        {"column": 0, "old": 28671617},
                        {"column": 4, "old": 1222582},
                        {"column": 6, "new": "4", "old": "44"},
                    ],
                    "table": "WhereAbouts_fails",
                    "type": "update",
                }
            ]
        }
    )


@pytest.fixture
def geodiff_real_coord_update_json():
    """Geodiff update with coordinate change."""
    # NOTE: PK are
    # columns: 0: address_id (AKA PROGRESSIVO_ACCESSO)
    # columns: 2: road_id (AKA PROGRESSIVO_NAZIONALE)
    return json.dumps(
        {
            "geodiff": [
                {
                    "changes": [
                        {"column": 0, "old": 28671616},
                        {
                            "column": 1,
                            "new": "R1AAAQAAAAABAQAAAAAAAICcwitAAAAAwInzREA=",
                            "old": "R1AAAQAAAAABAQAAAObiXKWtwitAXt3+bojzREA=",
                        },
                        {"column": 4, "old": 1222582},
                    ],
                    "table": "WhereAbouts_fails",
                    "type": "update",
                }
            ]
        }
    )


@pytest.fixture
def geodiff_delete_json():
    return json.dumps(
        {
            "geodiff": [
                {
                    "table": "simple",
                    "type": "delete",
                    "changes": [
                        {"column": 0, "old": 2},
                        {"column": 1, "old": "R1AAAeYQAAABAQAAAPBDGq/kSde/+HS2Feb94T8="},
                        {"column": 4, "old": 202},  # road_id should be integer
                        {"column": 3, "old": "feature2"},  # other field
                    ],
                }
            ]
        }
    )


@pytest.fixture
def geodiff_insert_json():
    return json.dumps(
        {
            "geodiff": [
                {
                    "table": "simple",
                    "type": "insert",
                    "changes": [
                        {"column": 0, "new": 4},
                        {"column": 1, "new": "R1AAAeYQAAABAQAAAFyu1BOp6um/PoMqH8N01j8="},
                        {"column": 4, "new": 401},  # road_id should be integer
                        {"column": 3, "new": "my new point A"},  # other field
                    ],
                }
            ]
        }
    )


@pytest.fixture
def geodiff_multiple_entries_json():
    """Geodiff with multiple entries of different types."""
    return json.dumps(
        {
            "geodiff": [
                {
                    "table": "addresses",
                    "type": "update",
                    "changes": [
                        {"column": 0, "old": 1001},
                        {"column": 1, "new": "R1AAAQAAAAABAQAAAAAAAICcwitAAAAAwInzREA="},
                        {"column": 4, "old": 5001},
                    ],
                },
                {
                    "table": "addresses",
                    "type": "insert",
                    "changes": [
                        {"column": 0, "new": 1002},
                        {"column": 1, "new": "R1AAAeYQAAABAQAAAFyu1BOp6um/PoMqH8N01j8="},
                        {"column": 4, "new": 5002},
                    ],
                },
                {
                    "table": "addresses",
                    "type": "delete",
                    "changes": [
                        {"column": 0, "old": 1003},
                        {"column": 1, "old": "R1AAAeYQAAABAQAAAPBDGq/kSde/+HS2Feb94T8="},
                        {"column": 4, "old": 5003},
                    ],
                },
            ]
        }
    )


@pytest.fixture
def geodiff_empty_json():
    """Empty geodiff file (no entries)."""
    return json.dumps({"geodiff": []})


@pytest.fixture
def geodiff_action_report_json():
    """Geodiff-action report format with header (has_changes, summary, changes)."""
    return json.dumps(
        {
            "base_file": "a_previous.gpkg",
            "compare_file": "a_current.gpkg",
            "has_changes": True,
            "summary": {
                "insert": 1,
                "update": 1,
                "delete": 0,
            },
            "changes": {
                "geodiff": [
                    {
                        "table": "addresses",
                        "type": "update",
                        "changes": [
                            {"column": 0, "old": 1001},
                            {"column": 1, "new": "R1AAAQAAAAABAQAAAAAAAICcwitAAAAAwInzREA="},
                            {"column": 4, "old": 5001},
                        ],
                    },
                    {
                        "table": "addresses",
                        "type": "insert",
                        "changes": [
                            {"column": 0, "new": 1002},
                            {"column": 1, "new": "R1AAAeYQAAABAQAAAFyu1BOp6um/PoMqH8N01j8="},
                            {"column": 4, "new": 5002},
                        ],
                    },
                ]
            },
        }
    )


# ============================================================================
# Fixtures - Geodiff Report Files (for integration tests)
# ============================================================================


@pytest.fixture
def geodiff_update_report_file(tmp_path):
    """Create a geodiff update report file as in test.yaml workflow.

    This mirrors the "Create geodiff fake update report" step in test.yaml.
    """
    report_content = {
        "geodiff": [
            {
                "changes": [
                    {"column": 0, "old": 28671617},
                    {"column": 4, "old": 1222582},
                    {"column": 6, "new": "4", "old": "44"},
                ],
                "table": "WhereAbouts_fails",
                "type": "update",
            }
        ]
    }
    report_file = tmp_path / "geodiff_update_report.json"
    report_file.write_text(json.dumps(report_content, indent=2))
    return report_file


@pytest.fixture
def geodiff_delete_report_file(tmp_path):
    """Create a geodiff delete report file.

    This mirrors the delete scenario in test-delete-check-with-geodiff.
    """
    report_content = {
        "geodiff": [
            {
                "table": "test_layer",
                "type": "delete",
                "changes": [
                    {"column": 0, "old": 2},
                    {"column": 1, "old": "R1AAAeYQAAABAQAAAPBDGq/kSde/+HS2Feb94T8="},
                    {"column": 3, "old": "Point B"},  # other field
                    {"column": 4, "old": 202},  # road_id should be integer
                    {"column": 5, "old": 2},
                ],
            },
            {
                "table": "test_layer",
                "type": "delete",
                "changes": [
                    {"column": 0, "old": 4},
                    {"column": 1, "old": "R1AAAeYQAAABAQAAAFyu1BOp6um/PoMqH8N01j8="},
                    {"column": 3, "old": "Point D"},  # other field
                    {"column": 4, "old": 404},  # road_id should be integer
                    {"column": 5, "old": 4},
                ],
            },
        ]
    }
    report_file = tmp_path / "geodiff_delete_report.json"
    report_file.write_text(json.dumps(report_content, indent=2))
    return report_file


@pytest.fixture
def geodiff_insert_report_file(tmp_path):
    """Create a geodiff insert report file.

    This mirrors the insert scenario in test-insert-check-with-geodiff.
    """
    report_content = {
        "geodiff": [
            {
                "table": "test_layer",
                "type": "insert",
                "changes": [
                    {"column": 0, "new": 6},
                    {"column": 1, "new": "R1AAAeYQAAABAQAAAFyu1BOp6um/PoMqH8N01j8="},
                    {"column": 3, "new": "Inserted Point F"},  # other field
                    {"column": 4, "new": 606},  # road_id should be integer
                    {"column": 5, "new": 6},
                ],
            },
            {
                "table": "test_layer",
                "type": "insert",
                "changes": [
                    {"column": 0, "new": 7},
                    {"column": 1, "new": "R1AAAeYQAAABAQAAAPBDGq/kSde/+HS2Feb94T8="},
                    {"column": 3, "new": "Inserted Point G"},  # other field
                    {"column": 4, "new": 707},  # road_id should be integer
                    {"column": 5, "new": 7},
                ],
            },
        ]
    }
    report_file = tmp_path / "geodiff_insert_report.json"
    report_file.write_text(json.dumps(report_content, indent=2))
    return report_file


@pytest.fixture
def geodiff_mixed_report_file(tmp_path):
    """Create a geodiff report with mixed operations (insert, update, delete).

    This tests processing multiple operation types in a single report.
    """
    report_content = {
        "geodiff": [
            {
                "table": "test_layer",
                "type": "update",
                "changes": [
                    {"column": 0, "old": 1},
                    {"column": 1, "new": "R1AAAQAAAAABAQAAAAAAAICcwitAAAAAwInzREA="},
                    {"column": 4, "old": 101},
                ],
            },
            {
                "table": "test_layer",
                "type": "insert",
                "changes": [
                    {"column": 0, "new": 10},
                    {"column": 1, "new": "R1AAAeYQAAABAQAAAFyu1BOp6um/PoMqH8N01j8="},
                    {"column": 4, "new": 1010},
                ],
            },
            {
                "table": "test_layer",
                "type": "delete",
                "changes": [
                    {"column": 0, "old": 5},
                    {"column": 1, "old": "R1AAAeYQAAABAQAAAPBDGq/kSde/+HS2Feb94T8="},
                    {"column": 4, "old": 505},
                ],
            },
        ]
    }
    report_file = tmp_path / "geodiff_mixed_report.json"
    report_file.write_text(json.dumps(report_content, indent=2))
    return report_file


@pytest.fixture
def geodiff_plugin_skip_report_file(tmp_path):
    """Report file with entries that have PLUGIN_SCORE=1.0 and PLUGIN_GEOCODER=ANNCSU.

    Both entries must be skipped by process_entry without any CLI calls.
    """
    report_content = {
        "geodiff": [
            {
                "table": "test_layer",
                "type": "update",
                "changes": [
                    {"column": 0, "old": 77001},
                    {"column": 1, "new": "R1AAAQAAAAABAQAAAAAAAICcwitAAAAAwInzREA="},
                    {"column": 4, "old": 7001},
                    {"column": 20, "old": None, "new": "1.0"},
                    {"column": 21, "old": None, "new": "ANNCSU"},
                ],
            },
            {
                "table": "test_layer",
                "type": "update",
                "changes": [
                    {"column": 0, "old": 77002},
                    {"column": 1, "new": "R1AAAeYQAAABAQAAAFyu1BOp6um/PoMqH8N01j8="},
                    {"column": 4, "old": 7002},
                    {"column": 20, "old": None, "new": "1.0"},
                    {"column": 21, "old": None, "new": "ANNCSU"},
                ],
            },
        ]
    }
    report_file = tmp_path / "geodiff_plugin_skip_report.json"
    report_file.write_text(json.dumps(report_content, indent=2))
    return report_file


@pytest.fixture
def geodiff_plugin_no_skip_report_file(tmp_path):
    """Report file with entries that have plugin columns but should NOT be skipped.

    One entry has PLUGIN_SCORE != 1.0, another has PLUGIN_GEOCODER != ANNCSU.
    Both must be processed normally (CLI calls expected).
    """
    report_content = {
        "geodiff": [
            {
                "table": "test_layer",
                "type": "update",
                "changes": [
                    {"column": 0, "old": 88001},
                    {"column": 1, "new": "R1AAAQAAAAABAQAAAAAAAICcwitAAAAAwInzREA="},
                    {"column": 4, "old": 8001},
                    {"column": 20, "old": None, "new": "0.75"},
                    {"column": 21, "old": None, "new": "ANNCSU"},
                ],
            },
            {
                "table": "test_layer",
                "type": "update",
                "changes": [
                    {"column": 0, "old": 88002},
                    {"column": 1, "new": "R1AAAeYQAAABAQAAAFyu1BOp6um/PoMqH8N01j8="},
                    {"column": 4, "old": 8002},
                    {"column": 20, "old": None, "new": "1.0"},
                    {"column": 21, "old": None, "new": "OTHER_GEOCODER"},
                ],
            },
        ]
    }
    report_file = tmp_path / "geodiff_plugin_no_skip_report.json"
    report_file.write_text(json.dumps(report_content, indent=2))
    return report_file


# ============================================================================
# Fixtures - GeoPackage files (for geodiff comparison tests)
# ============================================================================


@pytest.fixture
def base_geopackage(tmp_path):
    """Create a base GeoPackage file with test data.

    This mirrors the GeoPackage creation in the workflow steps.
    """
    import sqlite3

    gpkg_path = tmp_path / "base.gpkg"

    conn = sqlite3.connect(gpkg_path)
    cursor = conn.cursor()

    # Create required GeoPackage tables
    cursor.executescript("""
        CREATE TABLE gpkg_spatial_ref_sys (
            srs_name TEXT NOT NULL,
            srs_id INTEGER NOT NULL PRIMARY KEY,
            organization TEXT NOT NULL,
            organization_coordsys_id INTEGER NOT NULL,
            definition TEXT NOT NULL,
            description TEXT
        );

        CREATE TABLE gpkg_contents (
            table_name TEXT NOT NULL PRIMARY KEY,
            data_type TEXT NOT NULL,
            identifier TEXT UNIQUE,
            description TEXT DEFAULT '',
            last_change DATETIME NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
            min_x DOUBLE,
            min_y DOUBLE,
            max_x DOUBLE,
            max_y DOUBLE,
            srs_id INTEGER
        );

        CREATE TABLE gpkg_geometry_columns (
            table_name TEXT NOT NULL,
            column_name TEXT NOT NULL,
            geometry_type_name TEXT NOT NULL,
            srs_id INTEGER NOT NULL,
            z TINYINT NOT NULL,
            m TINYINT NOT NULL,
            CONSTRAINT pk_geom_cols PRIMARY KEY (table_name, column_name)
        );

        INSERT INTO gpkg_spatial_ref_sys VALUES (
            'WGS 84', 4326, 'EPSG', 4326,
            'GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563]],PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433]]',
            NULL
        );

        CREATE TABLE test_layer (
            fid INTEGER PRIMARY KEY AUTOINCREMENT,
            geom BLOB,
            name TEXT,
            address_id INTEGER,
            road_id INTEGER,
            plugin_score REAL,
            plugin_geocoder TEXT
        );

        INSERT INTO gpkg_contents VALUES (
            'test_layer', 'features', 'test_layer', '',
            datetime('now'), NULL, NULL, NULL, NULL, 4326
        );

        INSERT INTO gpkg_geometry_columns VALUES (
            'test_layer', 'geom', 'POINT', 4326, 0, 0
        );

        INSERT INTO test_layer (fid, name, address_id, road_id, plugin_score, plugin_geocoder) VALUES (1, 'Point A', 1, 101, NULL, NULL);
        INSERT INTO test_layer (fid, name, address_id, road_id, plugin_score, plugin_geocoder) VALUES (2, 'Point B', 2, 202, NULL, NULL);
        INSERT INTO test_layer (fid, name, address_id, road_id, plugin_score, plugin_geocoder) VALUES (3, 'Point C', 3, 303, 0.5, 'OTHER');
        INSERT INTO test_layer (fid, name, address_id, road_id, plugin_score, plugin_geocoder) VALUES (4, 'Point D', 4, 404, 1.0, 'ANNCSU');
        INSERT INTO test_layer (fid, name, address_id, road_id, plugin_score, plugin_geocoder) VALUES (5, 'Point E', 5, 505, 1.0, 'ANNCSU');
    """)

    conn.commit()
    conn.close()

    return gpkg_path


# ============================================================================
# Mock Classes for main() Function Testing
# ============================================================================


class MockCoreForMain:
    """Mock for actions.core module used in main() tests."""

    def __init__(self):
        self.messages = []
        self.failed_message = None
        self.version = "1.0.0-test"

    def get_version(self) -> str:
        return self.version

    def info(self, message: str) -> None:
        self.messages.append(("info", message))

    def debug(self, message: str) -> None:
        self.messages.append(("debug", message))

    def warn(self, message: str) -> None:
        self.messages.append(("warn", message))

    def error(self, message: str) -> None:
        self.messages.append(("error", message))

    def set_failed(self, message: str) -> None:
        self.failed_message = message

    def group(self, name: str) -> Any:
        @contextmanager
        def _cm():
            yield None

        return _cm()

    def get_input(self, name: str, required: bool = False) -> str:
        if name == "geodiff_report":
            return "/fake/geodiff_report.json"
        if name == "token":
            return "fake-token"
        return ""


class MockContextForMain:
    """Mock for actions.context module used in main() tests."""

    repo = {"name": "test-repo", "owner": "test-owner"}
    sha = "abc123"
    ref = "refs/heads/main"
    os = object()  # Mock os object that will be deleted in main()


class MockFunctionsForMain:
    """Mock for functions module used in main() tests."""

    @staticmethod
    def check_output(cmd: str, raise_on_error: bool) -> str:
        return "Mock output"


class MockSettingsForMain:
    """Mock settings class for main() tests."""

    def __init__(self):
        self.codice_comune = "I501"
        self.coordinate_distance_threshold = 0.001

    def model_dump_json(self) -> str:
        return '{"codice_comune": "I501", "coordinate_distance_threshold": 0.001}'


class MockCliRunnerForMain:
    """Mock Typer CLI runner for main() tests."""

    def invoke(self, app: Any, args: list[str]) -> Any:
        return SimpleNamespace(exit_code=0, output="OK")


class MockGeoDiffForMain:
    """Mock pygeodiff.GeoDiff class for main() tests."""

    def create_wkb_from_gpkg_header(self, data: bytes) -> list[bytes]:
        return [b"FAKE-WKB"]


class MockGeometryForMain:
    """Mock shapely geometry for main() tests."""

    is_valid = True
    geom_type = "Point"

    @property
    def coords(self):
        return [(12.34, 56.78)]


def mock_wkb_loads_for_main(data: bytes) -> MockGeometryForMain:
    """Mock shapely.wkb.loads function for main() tests."""
    return MockGeometryForMain()


# ============================================================================
# Fixtures for main() Function Testing
# ============================================================================


@pytest.fixture
def mock_imports(monkeypatch):
    """Mock all runtime imports in the main() function.

    This fixture patches the imports that happen inside main():
    - typer.testing.CliRunner
    - shapely.wkb
    - pygeodiff.GeoDiff
    - actions.context and core
    - functions
    - settings.AnncsuUpdateSettings
    - anncsu.cli.app
    """
    import sys
    import types

    # Create mock modules
    mock_typer_testing = types.ModuleType("typer.testing")
    mock_typer_testing.CliRunner = MockCliRunnerForMain

    mock_shapely_wkb = types.ModuleType("shapely.wkb")
    mock_shapely_wkb.loads = mock_wkb_loads_for_main

    mock_pygeodiff = types.ModuleType("pygeodiff")
    mock_pygeodiff.GeoDiff = MockGeoDiffForMain

    mock_actions = types.ModuleType("actions")
    mock_actions.core = MockCoreForMain()

    # Create context as a module-like object with proper attributes
    mock_context = types.SimpleNamespace()
    mock_context.repo = {"name": "test-repo", "owner": "test-owner"}
    mock_context.sha = "abc123"
    mock_context.ref = "refs/heads/main"
    mock_context.os = object()  # Will be deleted by main()
    mock_actions.context = mock_context

    mock_functions = MockFunctionsForMain()

    mock_settings_module = types.ModuleType("settings")
    mock_settings_module.AnncsuUpdateSettings = MockSettingsForMain

    mock_anncsu_cli = types.ModuleType("anncsu.cli")
    mock_anncsu_cli.app = SimpleNamespace(name="mock-anncsu-cli")

    # Patch sys.modules to inject our mocks
    monkeypatch.setitem(sys.modules, "typer.testing", mock_typer_testing)
    monkeypatch.setitem(sys.modules, "shapely.wkb", mock_shapely_wkb)
    monkeypatch.setitem(sys.modules, "pygeodiff", mock_pygeodiff)
    monkeypatch.setitem(sys.modules, "actions", mock_actions)
    monkeypatch.setitem(sys.modules, "functions", mock_functions)
    monkeypatch.setitem(sys.modules, "settings", mock_settings_module)
    monkeypatch.setitem(sys.modules, "anncsu.cli", mock_anncsu_cli)
    monkeypatch.setitem(sys.modules, "anncsu", types.ModuleType("anncsu"))

    return {
        "core": mock_actions.core,
        "context": mock_actions.context,
        "functions": mock_functions,
        "settings": mock_settings_module,
        "cli_app": mock_anncsu_cli.app,
    }


@pytest.fixture
def mock_run_action_success(monkeypatch):
    """Mock run_action to return True (success)."""

    def mock_run_action(*args, **kwargs):
        return True

    monkeypatch.setattr("main_with_cli.run_action", mock_run_action)


@pytest.fixture
def mock_run_action_failure(monkeypatch):
    """Mock run_action to return False (failure)."""

    def mock_run_action(*args, **kwargs):
        return False

    monkeypatch.setattr("main_with_cli.run_action", mock_run_action)


# ============================================================================
# Legacy Fixtures (for backward compatibility during transition)
# ============================================================================


@pytest.fixture
def fake_functions_module():
    """Legacy fixture - creates a fake functions module."""
    import types

    mod = types.ModuleType("functions")

    def fake_check_output(*_a, **_kw):
        return ""

    mod.check_output = fake_check_output
    return mod


@pytest.fixture
def make_fake_actions_module():
    """Legacy fixture - creates a fake actions module factory."""
    import types

    def _make(geodiff_report_text):
        mod = types.ModuleType("actions")

        class DummyCore:
            def __init__(self):
                self._failed = None

            def get_version(self):
                return "0.1"

            def info(self, *_a, **_kw):
                return None

            def debug(self, *_a, **_kw):
                return None

            def warn(self, *_a, **_kw):
                return None

            def error(self, *_a, **_kw):
                return None

            def set_failed(self, msg):
                self._failed = msg

            def group(self, *_a, **_kw):
                @contextmanager
                def _cm():
                    yield None

                return _cm()

            def get_input(self, name, required=False):
                if name == "geodiff_report":
                    return geodiff_report_text
                if name == "token":
                    return "FAKE-TOKEN"
                return ""

        context = SimpleNamespace(os=object(), repo={"name": "x"})
        core = DummyCore()

        mod.context = context
        mod.core = core
        return mod

    return _make


@pytest.fixture
def make_fake_settings_module():
    """Legacy fixture - creates a fake settings module factory."""
    import types

    def _make():
        mod = types.ModuleType("settings")

        class AnncsuUpdateSettings:
            def __init__(self):
                self.codice_comune = "I501"

            def model_dump_json(self):
                settings = """{
                    "ANNCSU_UPDATE_CODICE_COMUNE": "I501"
                }"""
                return settings.replace("\n", "").replace(" ", "")

        mod.AnncsuUpdateSettings = AnncsuUpdateSettings
        return mod

    return _make


@pytest.fixture
def make_fake_pygeodiff_and_shapely():
    """Legacy fixture - creates fake pygeodiff and shapely modules."""
    import types

    def _make():
        pygeodiff = types.ModuleType("pygeodiff")

        class GeoDiff:
            def create_wkb_from_gpkg_header(self, data):
                return [b"FAKE-WKB"]

        pygeodiff.GeoDiff = GeoDiff

        shapely = types.ModuleType("shapely")
        wkb = types.ModuleType("shapely.wkb")

        class FakeGeometry:
            is_valid = True
            geom_type = "Point"

            def __init__(self, coords):
                self._coords = coords

            @property
            def coords(self):
                return self._coords

        def loads(_bytes):
            return FakeGeometry([(12.34, 56.78)])

        wkb.loads = loads

        class Point:
            def __init__(self, coord):
                self.x, self.y = coord

        shapely.wkb = wkb
        shapely.Point = Point

        return pygeodiff, shapely

    return _make


@pytest.fixture
def DummyCliRunner():
    """Legacy fixture - dummy CLI runner class."""

    class DummyCliRunner:
        def invoke(self, app, args):
            return SimpleNamespace(exit_code=0, output="ok")

    return DummyCliRunner
