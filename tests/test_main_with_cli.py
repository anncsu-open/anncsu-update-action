"""Tests for main_with_cli module.

These tests use dependency injection to test individual functions
without requiring complex module mocking.
"""

import binascii
import pytest

from geodiff_models import GeodiffFile  # noqa: E402

# Import the module under test (now safe to import without side effects)
from main_with_cli import (
    Coordinates,
    EntryResult,
    decode_gpkg_geometry,
    extract_coordinates_from_geometry,
    parse_gpkg_to_coordinates,
    extract_entry_data,
    process_entry,
    process_all_entries,
    load_geodiff_report,
    authenticate_cli,
    run_action,
)

# Import mock classes for type hints (they're defined in conftest.py)
# We need to import them here since we use them as type annotations
# from conftest import MockLogger, MockSettings, MockCliRunner, MockCliResult, MockGeoDiff, MockGeometry, MockPoint
from conftest import (
    MockCliRunner,
    MockCliResult,
    MockGeometry,
    MockAnncsuConsultazione,
)


# ============================================================================
# Tests for Coordinates and EntryResult dataclasses
# ============================================================================


class TestDataClasses:
    def test_coordinates_creation(self):
        coords = Coordinates(x=12.34, y=56.78)
        assert coords.x == 12.34
        assert coords.y == 56.78

    def test_entry_result_success(self):
        result = EntryResult(entry_type="update", success=True)
        assert result.entry_type == "update"
        assert result.success is True
        assert result.error_message is None

    def test_entry_result_failure(self):
        result = EntryResult(entry_type="delete", success=False, error_message="Failed")
        assert result.entry_type == "delete"
        assert result.success is False
        assert result.error_message == "Failed"


# ============================================================================
# Tests for geometry parsing functions
# ============================================================================


class TestGeometryParsing:
    def test_decode_gpkg_geometry_success(self, mock_geodiff, mock_wkb_loader):
        gpkg_base64 = "R1AAAQAAAAABAQAAAAAAAICcwitAAAAAwInzREA="
        result = decode_gpkg_geometry(gpkg_base64, mock_geodiff, mock_wkb_loader)

        # Check the geometry has expected attributes
        assert result.is_valid
        assert result.geom_type == "Point"
        assert hasattr(result, "coords")

    def test_decode_gpkg_geometry_invalid_base64(self, mock_geodiff, mock_wkb_loader):
        with pytest.raises(binascii.Error):  # base64.binascii.Error
            decode_gpkg_geometry("not-valid-base64!!!", mock_geodiff, mock_wkb_loader)

    def test_extract_coordinates_from_geometry_success(self):
        geometry = MockGeometry(is_valid=True, geom_type="Point", _coords=[(10.5, 20.5)])
        coords = extract_coordinates_from_geometry(geometry)

        assert coords.x == 10.5
        assert coords.y == 20.5

    def test_extract_coordinates_from_geometry_invalid(self):
        geometry = MockGeometry(is_valid=False, geom_type="Point")

        with pytest.raises(ValueError, match="Invalid geometry"):
            extract_coordinates_from_geometry(geometry)

    def test_extract_coordinates_from_geometry_not_point(self):
        geometry = MockGeometry(is_valid=True, geom_type="LineString")

        with pytest.raises(ValueError, match="Geometry is not a Point"):
            extract_coordinates_from_geometry(geometry)

    def test_parse_gpkg_to_coordinates_success(self, mock_geodiff, mock_wkb_loader):
        gpkg_base64 = "R1AAAQAAAAABAQAAAAAAAICcwitAAAAAwInzREA="
        coords = parse_gpkg_to_coordinates(gpkg_base64, mock_geodiff, mock_wkb_loader)

        assert isinstance(coords, Coordinates)
        assert coords.x == 12.34
        assert coords.y == 56.78


# ============================================================================
# Tests for entry data extraction
# ============================================================================


class TestExtractEntryData:
    def test_extract_entry_data_update(self, geodiff_real_coord_update_json):
        geodiff = GeodiffFile.from_json_text(geodiff_real_coord_update_json)
        entry = geodiff.geodiff[0]

        address_id, road_id, gpkg_geom, plugin_score, plugin_geocoder = extract_entry_data(entry)

        assert address_id == 28671616
        assert road_id == 1222582
        assert gpkg_geom == "R1AAAQAAAAABAQAAAAAAAICcwitAAAAAwInzREA="
        assert plugin_score is None
        assert plugin_geocoder is None

    def test_extract_entry_data_insert(self, geodiff_insert_json):
        geodiff = GeodiffFile.from_json_text(geodiff_insert_json)
        entry = geodiff.geodiff[0]

        address_id, road_id, gpkg_geom, plugin_score, plugin_geocoder = extract_entry_data(entry)

        assert address_id == 4
        assert gpkg_geom == "R1AAAeYQAAABAQAAAFyu1BOp6um/PoMqH8N01j8="
        assert plugin_score is None
        assert plugin_geocoder is None

    def test_extract_entry_data_no_geometry(self, geodiff_real_value_update_json):
        geodiff = GeodiffFile.from_json_text(geodiff_real_value_update_json)
        entry = geodiff.geodiff[0]

        address_id, road_id, gpkg_geom, plugin_score, plugin_geocoder = extract_entry_data(entry)

        assert address_id == 28671617
        assert road_id == 1222582
        assert gpkg_geom is None
        assert plugin_score is None
        assert plugin_geocoder is None

    def test_extract_entry_data_with_plugin_score_and_geocoder(self):
        from types import SimpleNamespace

        entry = SimpleNamespace(
            type="update",
            table="addresses",
            changes=[
                SimpleNamespace(column=0, old=99001, new=None),
                SimpleNamespace(column=1, old=None, new="R1AAAQAAAAABAQAAAAAAAICcwitAAAAAwInzREA="),
                SimpleNamespace(column=4, old=5001, new=None),
                SimpleNamespace(column=20, old=None, new="1.0"),
                SimpleNamespace(column=21, old=None, new="ANNCSU"),
            ],
        )

        address_id, road_id, gpkg_geom, plugin_score, plugin_geocoder = extract_entry_data(entry)

        assert address_id == 99001
        assert road_id == 5001
        assert gpkg_geom == "R1AAAQAAAAABAQAAAAAAAICcwitAAAAAwInzREA="
        assert plugin_score == 1.0
        assert plugin_geocoder == "ANNCSU"

    def test_extract_entry_data_with_plugin_score_only(self):
        from types import SimpleNamespace

        entry = SimpleNamespace(
            type="update",
            table="addresses",
            changes=[
                SimpleNamespace(column=0, old=99002, new=None),
                SimpleNamespace(column=20, old=None, new="0.8"),
            ],
        )

        address_id, road_id, gpkg_geom, plugin_score, plugin_geocoder = extract_entry_data(entry)

        assert address_id == 99002
        assert plugin_score == 0.8
        assert plugin_geocoder is None

    def test_extract_entry_data_with_plugin_geocoder_only(self):
        from types import SimpleNamespace

        entry = SimpleNamespace(
            type="update",
            table="addresses",
            changes=[
                SimpleNamespace(column=0, old=99003, new=None),
                SimpleNamespace(column=21, old=None, new="OTHER"),
            ],
        )

        address_id, road_id, gpkg_geom, plugin_score, plugin_geocoder = extract_entry_data(entry)

        assert address_id == 99003
        assert plugin_score is None
        assert plugin_geocoder == "OTHER"

    def test_extract_entry_data_plugin_score_uses_old_when_new_is_none(self):
        from types import SimpleNamespace

        entry = SimpleNamespace(
            type="update",
            table="addresses",
            changes=[
                SimpleNamespace(column=0, old=99004, new=None),
                SimpleNamespace(column=20, old="1.0", new=None),
                SimpleNamespace(column=21, old="ANNCSU", new=None),
            ],
        )

        address_id, road_id, gpkg_geom, plugin_score, plugin_geocoder = extract_entry_data(entry)

        assert plugin_score == 1.0
        assert plugin_geocoder == "ANNCSU"


# ============================================================================
# Tests for process_entry function
# ============================================================================


class TestProcessEntry:
    def test_process_entry_update_success(
        self,
        geodiff_real_coord_update_json,
        mock_settings,
        mock_cli_runner,
        mock_cli_app,
        mock_geodiff,
        mock_wkb_loader,
        mock_logger,
        mock_anncsu_consultazione,
    ):
        geodiff = GeodiffFile.from_json_text(geodiff_real_coord_update_json)
        entry = geodiff.geodiff[0]

        result = process_entry(
            entry=entry,
            settings=mock_settings,
            cli_runner=mock_cli_runner,
            cli_app=mock_cli_app,
            anncsu_sdk=mock_anncsu_consultazione,
            geodiff=mock_geodiff,
            wkb_loader=mock_wkb_loader,
            logger=mock_logger,
        )

        assert result is True
        # Verify CLI was called: first query, then coordinate update
        assert len(mock_cli_runner.invocations) == 2
        _, query_args = mock_cli_runner.invocations[0]
        assert "pa" in query_args
        assert "accesso" in query_args
        _, update_args = mock_cli_runner.invocations[1]
        assert "coordinate" in update_args
        assert "update" in update_args
        assert "--codcom" in update_args
        assert "I501" in update_args

    def test_process_entry_update_cli_failure(
        self,
        geodiff_real_coord_update_json,
        mock_settings,
        mock_cli_app,
        mock_geodiff,
        mock_wkb_loader,
        mock_logger,
        mock_anncsu_consultazione,
    ):
        # Query succeeds with different coords (forces update), update call fails
        cli_runner = MockCliRunner(
            results_sequence=[
                MockCliResult(exit_code=0, output='[{"coordX": 10.0, "coordY": 50.0}]'),  # query OK
                MockCliResult(exit_code=1, output="Update failed"),  # update fails
            ]
        )

        geodiff = GeodiffFile.from_json_text(geodiff_real_coord_update_json)
        entry = geodiff.geodiff[0]

        result = process_entry(
            entry=entry,
            settings=mock_settings,
            cli_runner=cli_runner,
            cli_app=mock_cli_app,
            anncsu_sdk=mock_anncsu_consultazione,
            geodiff=mock_geodiff,
            wkb_loader=mock_wkb_loader,
            logger=mock_logger,
        )

        assert result is False
        # Check error was logged for coordinate update failure
        error_messages = [msg for level, msg in mock_logger.messages if level == "error"]
        assert any("failed" in msg.lower() for msg in error_messages)

    def test_process_entry_missing_geometry(
        self,
        geodiff_real_value_update_json,
        mock_settings,
        mock_cli_runner,
        mock_cli_app,
        mock_geodiff,
        mock_wkb_loader,
        mock_logger,
        mock_anncsu_consultazione,
    ):
        geodiff = GeodiffFile.from_json_text(geodiff_real_value_update_json)
        entry = geodiff.geodiff[0]

        result = process_entry(
            entry=entry,
            settings=mock_settings,
            cli_runner=mock_cli_runner,
            cli_app=mock_cli_app,
            anncsu_sdk=mock_anncsu_consultazione,
            geodiff=mock_geodiff,
            wkb_loader=mock_wkb_loader,
            logger=mock_logger,
        )

        assert result is False
        # Verify no CLI calls made
        assert len(mock_cli_runner.invocations) == 0
        # Check warning was logged
        warn_messages = [msg for level, msg in mock_logger.messages if level == "warn"]
        assert any("No geometry" in msg for msg in warn_messages)

    def test_process_entry_insert_success(
        self,
        geodiff_insert_json,
        mock_settings,
        mock_cli_runner,
        mock_cli_app,
        mock_geodiff,
        mock_wkb_loader,
        mock_logger,
        mock_anncsu_consultazione,
    ):
        geodiff = GeodiffFile.from_json_text(geodiff_insert_json)
        entry = geodiff.geodiff[0]

        result = process_entry(
            entry=entry,
            settings=mock_settings,
            cli_runner=mock_cli_runner,
            cli_app=mock_cli_app,
            anncsu_sdk=mock_anncsu_consultazione,
            geodiff=mock_geodiff,
            wkb_loader=mock_wkb_loader,
            logger=mock_logger,
        )

        assert result is True
        # Insert with positive address_id goes through the same update path
        info_messages = [msg for level, msg in mock_logger.messages if level == "info"]
        assert any("insert" in msg.lower() for msg in info_messages)

    def test_process_entry_delete_success(
        self,
        geodiff_delete_json,
        mock_settings,
        mock_cli_runner,
        mock_cli_app,
        mock_geodiff,
        mock_wkb_loader,
        mock_logger,
        mock_anncsu_consultazione,
    ):
        geodiff = GeodiffFile.from_json_text(geodiff_delete_json)
        entry = geodiff.geodiff[0]

        result = process_entry(
            entry=entry,
            settings=mock_settings,
            cli_runner=mock_cli_runner,
            cli_app=mock_cli_app,
            anncsu_sdk=mock_anncsu_consultazione,
            geodiff=mock_geodiff,
            wkb_loader=mock_wkb_loader,
            logger=mock_logger,
        )

        assert result is True
        # Delete currently doesn't make CLI calls (TODO in code)
        info_messages = [msg for level, msg in mock_logger.messages if level == "info"]
        assert any("Delete" in msg for msg in info_messages)

    def test_process_entry_invalid_geometry(
        self,
        geodiff_real_coord_update_json,
        mock_settings,
        mock_cli_runner,
        mock_cli_app,
        mock_geodiff,
        mock_logger,
        mock_anncsu_consultazione,
    ):
        # Create WKB loader that returns invalid geometry
        def bad_wkb_loader(data):
            return MockGeometry(is_valid=False)

        geodiff = GeodiffFile.from_json_text(geodiff_real_coord_update_json)
        entry = geodiff.geodiff[0]

        result = process_entry(
            entry=entry,
            settings=mock_settings,
            cli_runner=mock_cli_runner,
            cli_app=mock_cli_app,
            anncsu_sdk=mock_anncsu_consultazione,
            geodiff=mock_geodiff,
            wkb_loader=bad_wkb_loader,
            logger=mock_logger,
        )

        assert result is False
        warn_messages = [msg for level, msg in mock_logger.messages if level == "warn"]
        assert any("Geometry error" in msg for msg in warn_messages)

    def test_process_entry_non_point_geometry(
        self,
        geodiff_real_coord_update_json,
        mock_settings,
        mock_cli_runner,
        mock_cli_app,
        mock_geodiff,
        mock_logger,
        mock_anncsu_consultazione,
    ):
        # Create WKB loader that returns LineString geometry
        def linestring_wkb_loader(data):
            return MockGeometry(is_valid=True, geom_type="LineString")

        geodiff = GeodiffFile.from_json_text(geodiff_real_coord_update_json)
        entry = geodiff.geodiff[0]

        result = process_entry(
            entry=entry,
            settings=mock_settings,
            cli_runner=mock_cli_runner,
            cli_app=mock_cli_app,
            anncsu_sdk=mock_anncsu_consultazione,
            geodiff=mock_geodiff,
            wkb_loader=linestring_wkb_loader,
            logger=mock_logger,
        )

        assert result is False
        warn_messages = [msg for level, msg in mock_logger.messages if level == "warn"]
        assert any("not a Point" in msg for msg in warn_messages)

    def test_process_entry_unknown_action_type(
        self,
        mock_settings,
        mock_cli_runner,
        mock_cli_app,
        mock_geodiff,
        mock_wkb_loader,
        mock_logger,
        mock_anncsu_consultazione,
    ):
        # Create a mock entry with an unknown action type
        # We bypass Pydantic validation to test defensive code
        from types import SimpleNamespace

        mock_change = SimpleNamespace(column=0, old=1001, new=None)
        mock_geom_change = SimpleNamespace(column=1, old=None, new="R1AAAQAAAAABAQAAAAAAAICcwitAAAAAwInzREA=")
        entry = SimpleNamespace(
            type="unknown_action",
            table="addresses",
            changes=[mock_change, mock_geom_change],
        )

        result = process_entry(
            entry=entry,  # type: ignore[arg-type]  # Intentionally bypassing Pydantic validation
            settings=mock_settings,
            cli_runner=mock_cli_runner,
            cli_app=mock_cli_app,
            anncsu_sdk=mock_anncsu_consultazione,
            geodiff=mock_geodiff,
            wkb_loader=mock_wkb_loader,
            logger=mock_logger,
        )

        assert result is False
        # Check warning was logged about unknown action type
        warn_messages = [msg for level, msg in mock_logger.messages if level == "warn"]
        assert any("Unknown action type" in msg for msg in warn_messages)

    def test_process_entry_anncsu_no_record_found(
        self,
        geodiff_real_coord_update_json,
        mock_settings,
        mock_cli_app,
        mock_geodiff,
        mock_wkb_loader,
        mock_logger,
        mock_anncsu_consultazione,
    ):
        """Test when ANNCSU CLI query returns no records for the address_id."""
        cli_runner = MockCliRunner(
            query_result=MockCliResult(exit_code=0, output="[]"),
        )

        geodiff = GeodiffFile.from_json_text(geodiff_real_coord_update_json)
        entry = geodiff.geodiff[0]

        result = process_entry(
            entry=entry,
            settings=mock_settings,
            cli_runner=cli_runner,
            cli_app=mock_cli_app,
            anncsu_sdk=mock_anncsu_consultazione,
            geodiff=mock_geodiff,
            wkb_loader=mock_wkb_loader,
            logger=mock_logger,
        )

        assert result is False
        warn_messages = [msg for level, msg in mock_logger.messages if level == "warn"]
        assert any("No ANNCSU record found" in msg for msg in warn_messages)

    def test_process_entry_anncsu_multiple_records_found(
        self,
        geodiff_real_coord_update_json,
        mock_settings,
        mock_cli_app,
        mock_geodiff,
        mock_wkb_loader,
        mock_logger,
        mock_anncsu_consultazione,
    ):
        """Test when ANNCSU CLI query returns multiple records for the address_id."""
        cli_runner = MockCliRunner(
            query_result=MockCliResult(
                exit_code=0,
                output='[{"coordX": 10.0, "coordY": 50.0}, {"coordX": 11.0, "coordY": 51.0}]',
            ),
        )

        geodiff = GeodiffFile.from_json_text(geodiff_real_coord_update_json)
        entry = geodiff.geodiff[0]

        result = process_entry(
            entry=entry,
            settings=mock_settings,
            cli_runner=cli_runner,
            cli_app=mock_cli_app,
            anncsu_sdk=mock_anncsu_consultazione,
            geodiff=mock_geodiff,
            wkb_loader=mock_wkb_loader,
            logger=mock_logger,
        )

        assert result is False
        warn_messages = [msg for level, msg in mock_logger.messages if level == "warn"]
        assert any("Multiple ANNCSU records found" in msg for msg in warn_messages)

    def test_process_entry_anncsu_query_failure(
        self,
        geodiff_real_coord_update_json,
        mock_settings,
        mock_cli_app,
        mock_geodiff,
        mock_wkb_loader,
        mock_logger,
        mock_anncsu_consultazione,
    ):
        """Test when ANNCSU CLI query call fails (non-zero exit code)."""
        cli_runner = MockCliRunner(
            result=MockCliResult(exit_code=1, output="Query failed"),
        )

        geodiff = GeodiffFile.from_json_text(geodiff_real_coord_update_json)
        entry = geodiff.geodiff[0]

        result = process_entry(
            entry=entry,
            settings=mock_settings,
            cli_runner=cli_runner,
            cli_app=mock_cli_app,
            anncsu_sdk=mock_anncsu_consultazione,
            geodiff=mock_geodiff,
            wkb_loader=mock_wkb_loader,
            logger=mock_logger,
        )

        assert result is False
        error_messages = [msg for level, msg in mock_logger.messages if level == "error"]
        assert any("Failed to query ANNCSU" in msg for msg in error_messages)

    def test_process_entry_coordinates_within_threshold(
        self,
        geodiff_real_coord_update_json,
        mock_settings,
        mock_cli_app,
        mock_geodiff,
        mock_wkb_loader,
        mock_logger,
        mock_anncsu_consultazione,
    ):
        """Test when coordinates are within threshold - should skip update."""
        # CLI query returns same coordinates as mock_wkb_loader (12.34, 56.78)
        cli_runner = MockCliRunner(
            query_result=MockCliResult(
                exit_code=0,
                output='[{"coordX": 12.34, "coordY": 56.78}]',
            ),
        )

        geodiff = GeodiffFile.from_json_text(geodiff_real_coord_update_json)
        entry = geodiff.geodiff[0]

        result = process_entry(
            entry=entry,
            settings=mock_settings,
            cli_runner=cli_runner,
            cli_app=mock_cli_app,
            anncsu_sdk=mock_anncsu_consultazione,
            geodiff=mock_geodiff,
            wkb_loader=mock_wkb_loader,
            logger=mock_logger,
        )

        assert result is True
        # Only the query CLI call should have been made (no update)
        assert len(cli_runner.invocations) == 1
        info_messages = [msg for level, msg in mock_logger.messages if level == "info"]
        assert any("Coordinates" in msg and "are the same" in msg for msg in info_messages)

    def test_process_entry_insert_negative_address_id(
        self,
        mock_settings,
        mock_cli_runner,
        mock_cli_app,
        mock_geodiff,
        mock_wkb_loader,
        mock_logger,
        mock_anncsu_consultazione,
    ):
        """Test insert with negative address_id (new record without assigned ID)."""
        from types import SimpleNamespace

        # Create an insert entry with negative address_id
        mock_change_addr = SimpleNamespace(column=0, old=None, new=-1)
        mock_change_geom = SimpleNamespace(column=1, old=None, new="R1AAAQAAAAABAQAAAAAAAICcwitAAAAAwInzREA=")
        mock_change_road = SimpleNamespace(column=4, old=None, new=5001)
        entry = SimpleNamespace(
            type="insert",
            table="addresses",
            changes=[mock_change_addr, mock_change_geom, mock_change_road],
        )

        result = process_entry(
            entry=entry,  # type: ignore[arg-type]
            settings=mock_settings,
            cli_runner=mock_cli_runner,
            cli_app=mock_cli_app,
            anncsu_sdk=mock_anncsu_consultazione,
            geodiff=mock_geodiff,
            wkb_loader=mock_wkb_loader,
            logger=mock_logger,
        )

        assert result is False
        warn_messages = [msg for level, msg in mock_logger.messages if level == "warn"]
        assert any("Insert action with negative address_id" in msg for msg in warn_messages)

    def test_process_entry_skipped_when_insert_with_plugin_score_1_and_geocoder_anncsu(
        self,
        mock_settings,
        mock_cli_runner,
        mock_cli_app,
        mock_geodiff,
        mock_wkb_loader,
        mock_logger,
        mock_anncsu_consultazione,
    ):
        """Insert entry with PLUGIN_SCORE=1.0 and PLUGIN_GEOCODER=ANNCSU must be skipped (no CLI calls).

        This represents an original unmodified ANNCSU record being inserted for the first time.
        """
        from types import SimpleNamespace

        entry = SimpleNamespace(
            type="insert",
            table="addresses",
            changes=[
                SimpleNamespace(column=0, old=None, new=50001),
                SimpleNamespace(column=1, old=None, new="R1AAAQAAAAABAQAAAAAAAICcwitAAAAAwInzREA="),
                SimpleNamespace(column=4, old=None, new=9001),
                SimpleNamespace(column=20, old=None, new="1.0"),
                SimpleNamespace(column=21, old=None, new="ANNCSU"),
            ],
        )

        result = process_entry(
            entry=entry,  # type: ignore[arg-type]
            settings=mock_settings,
            cli_runner=mock_cli_runner,
            cli_app=mock_cli_app,
            anncsu_sdk=mock_anncsu_consultazione,
            geodiff=mock_geodiff,
            wkb_loader=mock_wkb_loader,
            logger=mock_logger,
        )

        assert result is True
        assert len(mock_cli_runner.invocations) == 0
        info_messages = [msg for level, msg in mock_logger.messages if level == "info"]
        assert any("PLUGIN_SCORE=1.0" in msg and "PLUGIN_GEOCODER=ANNCSU" in msg for msg in info_messages)

    def test_process_entry_update_not_skipped_when_plugin_score_1_and_geocoder_anncsu(
        self,
        mock_settings,
        mock_cli_runner,
        mock_cli_app,
        mock_geodiff,
        mock_wkb_loader,
        mock_logger,
        mock_anncsu_consultazione,
    ):
        """Update entry with PLUGIN_SCORE=1.0 and PLUGIN_GEOCODER=ANNCSU must NOT be skipped.

        The skip-if-unmodified logic only applies to insert actions, not updates.
        """
        from types import SimpleNamespace

        entry = SimpleNamespace(
            type="update",
            table="addresses",
            changes=[
                SimpleNamespace(column=0, old=50006, new=None),
                SimpleNamespace(column=1, old=None, new="R1AAAQAAAAABAQAAAAAAAICcwitAAAAAwInzREA="),
                SimpleNamespace(column=4, old=9006, new=None),
                SimpleNamespace(column=20, old=None, new="1.0"),
                SimpleNamespace(column=21, old=None, new="ANNCSU"),
            ],
        )

        result = process_entry(
            entry=entry,  # type: ignore[arg-type]
            settings=mock_settings,
            cli_runner=mock_cli_runner,
            cli_app=mock_cli_app,
            anncsu_sdk=mock_anncsu_consultazione,
            geodiff=mock_geodiff,
            wkb_loader=mock_wkb_loader,
            logger=mock_logger,
        )

        assert result is True
        # CLI must have been called (query + coordinate update)
        assert len(mock_cli_runner.invocations) >= 1

    def test_process_entry_not_skipped_when_plugin_score_not_1(
        self,
        mock_settings,
        mock_cli_runner,
        mock_cli_app,
        mock_geodiff,
        mock_wkb_loader,
        mock_logger,
        mock_anncsu_consultazione,
    ):
        """Entry with PLUGIN_SCORE != 1.0 must NOT be skipped even if PLUGIN_GEOCODER=ANNCSU."""
        from types import SimpleNamespace

        entry = SimpleNamespace(
            type="update",
            table="addresses",
            changes=[
                SimpleNamespace(column=0, old=50002, new=None),
                SimpleNamespace(column=1, old=None, new="R1AAAQAAAAABAQAAAAAAAICcwitAAAAAwInzREA="),
                SimpleNamespace(column=4, old=9002, new=None),
                SimpleNamespace(column=20, old=None, new="0.5"),
                SimpleNamespace(column=21, old=None, new="ANNCSU"),
            ],
        )

        result = process_entry(
            entry=entry,  # type: ignore[arg-type]
            settings=mock_settings,
            cli_runner=mock_cli_runner,
            cli_app=mock_cli_app,
            anncsu_sdk=mock_anncsu_consultazione,
            geodiff=mock_geodiff,
            wkb_loader=mock_wkb_loader,
            logger=mock_logger,
        )

        assert result is True
        # CLI must have been called (query + update)
        assert len(mock_cli_runner.invocations) >= 1

    def test_process_entry_not_skipped_when_plugin_geocoder_not_anncsu(
        self,
        mock_settings,
        mock_cli_runner,
        mock_cli_app,
        mock_geodiff,
        mock_wkb_loader,
        mock_logger,
        mock_anncsu_consultazione,
    ):
        """Entry with PLUGIN_GEOCODER != ANNCSU must NOT be skipped even if PLUGIN_SCORE=1.0."""
        from types import SimpleNamespace

        entry = SimpleNamespace(
            type="update",
            table="addresses",
            changes=[
                SimpleNamespace(column=0, old=50003, new=None),
                SimpleNamespace(column=1, old=None, new="R1AAAQAAAAABAQAAAAAAAICcwitAAAAAwInzREA="),
                SimpleNamespace(column=4, old=9003, new=None),
                SimpleNamespace(column=20, old=None, new="1.0"),
                SimpleNamespace(column=21, old=None, new="OTHER_GEOCODER"),
            ],
        )

        result = process_entry(
            entry=entry,  # type: ignore[arg-type]
            settings=mock_settings,
            cli_runner=mock_cli_runner,
            cli_app=mock_cli_app,
            anncsu_sdk=mock_anncsu_consultazione,
            geodiff=mock_geodiff,
            wkb_loader=mock_wkb_loader,
            logger=mock_logger,
        )

        assert result is True
        assert len(mock_cli_runner.invocations) >= 1

    def test_process_entry_not_skipped_when_plugin_fields_none(
        self,
        mock_settings,
        mock_cli_runner,
        mock_cli_app,
        mock_geodiff,
        mock_wkb_loader,
        mock_logger,
        mock_anncsu_consultazione,
    ):
        """Entry without PLUGIN_SCORE/PLUGIN_GEOCODER columns must NOT be skipped."""
        from types import SimpleNamespace

        entry = SimpleNamespace(
            type="update",
            table="addresses",
            changes=[
                SimpleNamespace(column=0, old=50004, new=None),
                SimpleNamespace(column=1, old=None, new="R1AAAQAAAAABAQAAAAAAAICcwitAAAAAwInzREA="),
                SimpleNamespace(column=4, old=9004, new=None),
            ],
        )

        result = process_entry(
            entry=entry,  # type: ignore[arg-type]
            settings=mock_settings,
            cli_runner=mock_cli_runner,
            cli_app=mock_cli_app,
            anncsu_sdk=mock_anncsu_consultazione,
            geodiff=mock_geodiff,
            wkb_loader=mock_wkb_loader,
            logger=mock_logger,
        )

        assert result is True
        assert len(mock_cli_runner.invocations) >= 1

    def test_process_entry_not_skipped_when_only_plugin_score_present(
        self,
        mock_settings,
        mock_cli_runner,
        mock_cli_app,
        mock_geodiff,
        mock_wkb_loader,
        mock_logger,
        mock_anncsu_consultazione,
    ):
        """Entry with PLUGIN_SCORE=1.0 but no PLUGIN_GEOCODER must NOT be skipped."""
        from types import SimpleNamespace

        entry = SimpleNamespace(
            type="update",
            table="addresses",
            changes=[
                SimpleNamespace(column=0, old=50005, new=None),
                SimpleNamespace(column=1, old=None, new="R1AAAQAAAAABAQAAAAAAAICcwitAAAAAwInzREA="),
                SimpleNamespace(column=4, old=9005, new=None),
                SimpleNamespace(column=20, old=None, new="1.0"),
            ],
        )

        result = process_entry(
            entry=entry,  # type: ignore[arg-type]
            settings=mock_settings,
            cli_runner=mock_cli_runner,
            cli_app=mock_cli_app,
            anncsu_sdk=mock_anncsu_consultazione,
            geodiff=mock_geodiff,
            wkb_loader=mock_wkb_loader,
            logger=mock_logger,
        )

        assert result is True
        assert len(mock_cli_runner.invocations) >= 1


# ============================================================================
# Tests for process_all_entries function
# ============================================================================


class TestProcessAllEntries:
    def test_process_all_entries_multiple(
        self,
        geodiff_multiple_entries_json,
        mock_settings,
        mock_cli_runner,
        mock_cli_app,
        mock_geodiff,
        mock_wkb_loader,
        mock_logger,
        mock_anncsu_consultazione,
    ):
        geodiff = GeodiffFile.from_json_text(geodiff_multiple_entries_json)

        results = process_all_entries(
            geodiff_file=geodiff,
            settings=mock_settings,
            cli_runner=mock_cli_runner,
            cli_app=mock_cli_app,
            geodiff=mock_geodiff,
            wkb_loader=mock_wkb_loader,
            logger=mock_logger,
            anncsu_sdk=mock_anncsu_consultazione,
        )

        assert len(results) == 3
        assert results[0].entry_type == "update"
        assert results[1].entry_type == "insert"
        assert results[2].entry_type == "delete"
        assert all(r.success for r in results)

    def test_process_all_entries_empty(
        self,
        geodiff_empty_json,
        mock_settings,
        mock_cli_runner,
        mock_cli_app,
        mock_geodiff,
        mock_wkb_loader,
        mock_logger,
        mock_anncsu_consultazione,
    ):
        geodiff = GeodiffFile.from_json_text(geodiff_empty_json)

        results = process_all_entries(
            geodiff_file=geodiff,
            settings=mock_settings,
            cli_runner=mock_cli_runner,
            cli_app=mock_cli_app,
            geodiff=mock_geodiff,
            wkb_loader=mock_wkb_loader,
            logger=mock_logger,
            anncsu_sdk=mock_anncsu_consultazione,
        )

        assert len(results) == 0

    def test_process_all_entries_partial_failure(
        self,
        geodiff_multiple_entries_json,
        mock_settings,
        mock_cli_app,
        mock_geodiff,
        mock_logger,
        mock_anncsu_consultazione,
    ):
        # Entry 1 (update): query succeeds → update succeeds
        # Entry 2 (insert): invalid geometry → fails before any CLI call
        # Entry 3 (delete): returns True without CLI calls
        cli_runner = MockCliRunner(
            results_sequence=[
                MockCliResult(exit_code=0, output='[{"coordX": 10.0, "coordY": 50.0}]'),  # query for entry 1
                MockCliResult(exit_code=0, output="{}"),  # update for entry 1
            ]
        )

        # WKB loader that returns invalid geometry for second entry
        call_count = [0]

        def selective_wkb_loader(data):
            call_count[0] += 1
            if call_count[0] == 2:  # Second entry
                return MockGeometry(is_valid=False)
            return MockGeometry()

        geodiff = GeodiffFile.from_json_text(geodiff_multiple_entries_json)

        results = process_all_entries(
            geodiff_file=geodiff,
            settings=mock_settings,
            cli_runner=cli_runner,
            cli_app=mock_cli_app,
            geodiff=mock_geodiff,
            wkb_loader=selective_wkb_loader,
            logger=mock_logger,
            anncsu_sdk=mock_anncsu_consultazione,
        )

        assert len(results) == 3
        # Second entry should fail due to invalid geometry
        assert results[1].success is False


# ============================================================================
# Tests for load_geodiff_report function
# ============================================================================


class TestLoadGeodiffReport:
    def test_load_from_file(self, tmp_path, geodiff_real_coord_update_json, mock_logger):
        report_file = tmp_path / "report.json"
        report_file.write_text(geodiff_real_coord_update_json)

        result = load_geodiff_report(str(report_file), mock_logger)

        assert result is not None
        assert len(result.geodiff) == 1
        assert result.geodiff[0].type == "update"

    def test_load_from_json_text(self, geodiff_real_coord_update_json, mock_logger):
        result = load_geodiff_report(geodiff_real_coord_update_json, mock_logger)

        assert result is not None
        assert len(result.geodiff) == 1

    def test_load_invalid_json(self, mock_logger):
        result = load_geodiff_report("not valid json", mock_logger)

        assert result is None
        error_messages = [msg for level, msg in mock_logger.messages if level == "error"]
        assert len(error_messages) > 0

    def test_load_nonexistent_file_fallback_to_json(self, mock_logger):
        # Path doesn't exist, should try to parse as JSON
        result = load_geodiff_report("/nonexistent/path.json", mock_logger)

        assert result is None  # Invalid JSON

    def test_load_file_with_invalid_json(self, tmp_path, mock_logger):
        report_file = tmp_path / "bad_report.json"
        report_file.write_text("not valid json content")

        result = load_geodiff_report(str(report_file), mock_logger)

        assert result is None
        error_messages = [msg for level, msg in mock_logger.messages if level == "error"]
        assert any("Failed to parse" in msg for msg in error_messages)

    def test_load_geodiff_action_report_from_file(self, tmp_path, geodiff_action_report_json, mock_logger):
        """Test loading a geodiff-action report file with header."""
        report_file = tmp_path / "action_report.json"
        report_file.write_text(geodiff_action_report_json)

        result = load_geodiff_report(str(report_file), mock_logger)

        assert result is not None
        assert len(result.geodiff) == 2
        assert result.geodiff[0].type == "update"
        assert result.geodiff[1].type == "insert"
        # Verify the header was detected
        info_messages = [msg for level, msg in mock_logger.messages if level == "info"]
        assert any("Geodiff-action report file detected" in msg for msg in info_messages)

    def test_load_geodiff_action_report_from_json_text(self, geodiff_action_report_json, mock_logger):
        """Test loading geodiff-action report as JSON text (should fail and fall back)."""
        # When passed as JSON text (not a file), it should try to parse directly
        # The geodiff-action format is only detected when reading from a file
        result = load_geodiff_report(geodiff_action_report_json, mock_logger)

        # Should fail because the JSON text has the wrong structure for direct parsing
        assert result is None

    def test_load_geodiff_action_report_missing_changes_key(self, tmp_path, mock_logger):
        """Test geodiff-action report file with missing 'changes' key."""
        import json

        report_content = {"has_changes": True, "summary": {"insert": 0}}
        report_file = tmp_path / "incomplete_action_report.json"
        report_file.write_text(json.dumps(report_content))

        result = load_geodiff_report(str(report_file), mock_logger)

        # Should fail to parse as geodiff-action format and fall back to standard parsing
        assert result is None

    def test_load_geodiff_action_report_no_changes(self, tmp_path, mock_logger):
        """Test geodiff-action report with has_changes=False."""
        import json

        report_content = {
            "has_changes": False,
            "summary": {"insert": 0, "update": 0, "delete": 0},
            "changes": {"geodiff": []},
        }
        report_file = tmp_path / "no_changes_report.json"
        report_file.write_text(json.dumps(report_content))

        result = load_geodiff_report(str(report_file), mock_logger)

        assert result is not None
        assert len(result.geodiff) == 0


# ============================================================================
# Tests for authenticate_cli function
# ============================================================================


class TestAuthenticateCli:
    def test_authenticate_success(self, mock_cli_runner, mock_cli_app, mock_logger):
        result = authenticate_cli(mock_cli_runner, mock_cli_app, "pa", mock_logger)

        assert result is True
        assert len(mock_cli_runner.invocations) == 1
        _, args = mock_cli_runner.invocations[0]
        assert "auth" in args
        assert "login" in args
        assert "--api" in args
        assert "pa" in args

    def test_authenticate_failure(self, mock_cli_app, mock_logger):
        cli_runner = MockCliRunner(result=MockCliResult(exit_code=1, output="Auth failed"))

        result = authenticate_cli(cli_runner, mock_cli_app, "pa", mock_logger)

        assert result is False
        error_messages = [msg for level, msg in mock_logger.messages if level == "error"]
        assert any("authentication failed" in msg.lower() for msg in error_messages)

    def test_authenticate_exception(self, mock_cli_app, mock_logger):
        class FailingCliRunner:
            def invoke(self, app, args):
                raise RuntimeError("Network error")

        result = authenticate_cli(FailingCliRunner(), mock_cli_app, "pa", mock_logger)

        assert result is False
        error_messages = [msg for level, msg in mock_logger.messages if level == "error"]
        assert any("Failed to authenticate" in msg for msg in error_messages)


# ============================================================================
# Tests for run_action function
# ============================================================================


class TestRunAction:
    def test_run_action_success(
        self,
        geodiff_real_coord_update_json,
        mock_settings,
        mock_cli_runner,
        mock_cli_app,
        mock_geodiff,
        mock_wkb_loader,
        mock_logger,
        monkeypatch,
    ):
        # Mock the AnncsuConsultazione SDK
        monkeypatch.setattr(
            "main_with_cli.AnncsuConsultazione",
            lambda security: MockAnncsuConsultazione(security),
        )

        result = run_action(
            geodiff_report=geodiff_real_coord_update_json,
            settings=mock_settings,
            cli_runner=mock_cli_runner,
            cli_app=mock_cli_app,
            geodiff=mock_geodiff,
            wkb_loader=mock_wkb_loader,
            logger=mock_logger,
            token="test-token",
        )

        assert result is True
        # Should have auth + update calls
        assert len(mock_cli_runner.invocations) >= 2

    def test_run_action_invalid_report(
        self,
        mock_settings,
        mock_cli_runner,
        mock_cli_app,
        mock_geodiff,
        mock_wkb_loader,
        mock_logger,
    ):
        result = run_action(
            geodiff_report="invalid json",
            settings=mock_settings,
            cli_runner=mock_cli_runner,
            cli_app=mock_cli_app,
            geodiff=mock_geodiff,
            wkb_loader=mock_wkb_loader,
            logger=mock_logger,
            token="test-token",
        )

        assert result is False
        # Verify error was logged
        error_messages = [msg for level, msg in mock_logger.messages if level == "error"]
        assert len(error_messages) > 0
        assert any("geodiff report" in msg.lower() for msg in error_messages)

    def test_run_action_auth_failure(
        self,
        geodiff_real_coord_update_json,
        mock_settings,
        mock_cli_app,
        mock_geodiff,
        mock_wkb_loader,
        mock_logger,
    ):
        cli_runner = MockCliRunner(result=MockCliResult(exit_code=1, output="Auth failed"))

        result = run_action(
            geodiff_report=geodiff_real_coord_update_json,
            settings=mock_settings,
            cli_runner=cli_runner,
            cli_app=mock_cli_app,
            geodiff=mock_geodiff,
            wkb_loader=mock_wkb_loader,
            logger=mock_logger,
            token="test-token",
        )

        assert result is False
        # Verify error was logged
        error_messages = [msg for level, msg in mock_logger.messages if level == "error"]
        assert len(error_messages) > 0
        assert any("authenticate" in msg.lower() for msg in error_messages)

    def test_run_action_partial_entry_failure(
        self,
        geodiff_real_value_update_json,  # No geometry, will fail
        mock_settings,
        mock_cli_runner,
        mock_cli_app,
        mock_geodiff,
        mock_wkb_loader,
        mock_logger,
    ):
        result = run_action(
            geodiff_report=geodiff_real_value_update_json,
            settings=mock_settings,
            cli_runner=mock_cli_runner,
            cli_app=mock_cli_app,
            geodiff=mock_geodiff,
            wkb_loader=mock_wkb_loader,
            logger=mock_logger,
            token="test-token",
        )

        assert result is False
        warn_messages = [msg for level, msg in mock_logger.messages if level == "warn"]
        assert any("failed" in msg.lower() for msg in warn_messages)

    def test_run_action_with_file(
        self,
        tmp_path,
        geodiff_real_coord_update_json,
        mock_settings,
        mock_cli_runner,
        mock_cli_app,
        mock_geodiff,
        mock_wkb_loader,
        mock_logger,
        monkeypatch,
    ):
        # Mock the AnncsuConsultazione SDK
        monkeypatch.setattr(
            "main_with_cli.AnncsuConsultazione",
            lambda security: MockAnncsuConsultazione(security),
        )

        report_file = tmp_path / "report.json"
        report_file.write_text(geodiff_real_coord_update_json)

        result = run_action(
            geodiff_report=str(report_file),
            settings=mock_settings,
            cli_runner=mock_cli_runner,
            cli_app=mock_cli_app,
            geodiff=mock_geodiff,
            wkb_loader=mock_wkb_loader,
            logger=mock_logger,
            token="test-token",
        )

        assert result is True

    def test_run_action_empty_geodiff(
        self,
        geodiff_empty_json,
        mock_settings,
        mock_cli_runner,
        mock_cli_app,
        mock_geodiff,
        mock_wkb_loader,
        mock_logger,
    ):
        result = run_action(
            geodiff_report=geodiff_empty_json,
            settings=mock_settings,
            cli_runner=mock_cli_runner,
            cli_app=mock_cli_app,
            geodiff=mock_geodiff,
            wkb_loader=mock_wkb_loader,
            logger=mock_logger,
            token="test-token",
        )

        assert result is True  # Empty is success (nothing to do)
