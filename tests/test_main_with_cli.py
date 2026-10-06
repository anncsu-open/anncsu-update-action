"""Tests for main_with_cli module.

These tests use dependency injection to test individual functions
without requiring complex module mocking.
"""

import base64
import binascii
import json
import pytest

from geodiff_models import Change, GeodiffEntryDict, GeodiffFile  # noqa: E402

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
    load_geodiff_schema,
    authenticate_cli,
    run_action,
)

# Import mock classes for type hints (they're defined in conftest.py)
# We need to import them here since we use them as type annotations
# from conftest import MockLogger, MockSettings, MockCliRunner, MockCliResult, MockGeoDiff, MockGeometry, MockPoint
import main_with_cli

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
    def test_extract_entry_data_update(self, geodiff_schema, geodiff_real_coord_update_json):
        geodiff = GeodiffFile.from_json_text(geodiff_real_coord_update_json)
        entry = geodiff.geodiff[0]

        address_id, road_id, gpkg_geom, plugin_score, plugin_geocoder, plugin_sezioni_censimento = extract_entry_data(
            GeodiffEntryDict.from_entry(entry, geodiff_schema)
        )

        assert address_id == 28671616
        assert road_id == 1222582
        assert gpkg_geom == "R1AAAQAAAAABAQAAAAAAAICcwitAAAAAwInzREA="
        assert plugin_score is None
        assert plugin_geocoder is None
        assert plugin_sezioni_censimento is None

    def test_extract_entry_data_insert(self, geodiff_schema, geodiff_insert_json):
        geodiff = GeodiffFile.from_json_text(geodiff_insert_json)
        entry = geodiff.geodiff[0]

        address_id, road_id, gpkg_geom, plugin_score, plugin_geocoder, plugin_sezioni_censimento = extract_entry_data(
            GeodiffEntryDict.from_entry(entry, geodiff_schema)
        )

        assert address_id == -4
        assert gpkg_geom == "R1AAAeYQAAABAQAAAFyu1BOp6um/PoMqH8N01j8="
        assert plugin_score is None
        assert plugin_geocoder is None

    def test_extract_entry_data_no_geometry(self, geodiff_schema, geodiff_real_value_update_json):
        geodiff = GeodiffFile.from_json_text(geodiff_real_value_update_json)
        entry = geodiff.geodiff[0]

        address_id, road_id, gpkg_geom, plugin_score, plugin_geocoder, plugin_sezioni_censimento = extract_entry_data(
            GeodiffEntryDict.from_entry(entry, geodiff_schema)
        )

        assert address_id == 28671617
        assert road_id == 1222582
        assert gpkg_geom is None
        assert plugin_score is None
        assert plugin_geocoder is None

    def test_extract_entry_data_with_plugin_score_and_geocoder(self, geodiff_schema):
        from types import SimpleNamespace

        entry = SimpleNamespace(
            type="update",
            table="addresses",
            changes=[
                Change(column=0, old=99001, new=None),
                Change(column=1, old=None, new="R1AAAQAAAAABAQAAAAAAAICcwitAAAAAwInzREA="),
                Change(column=4, old=5001, new=None),
                Change(column=20, old=None, new="1.0"),
                Change(column=21, old=None, new="ANNCSU"),
            ],
        )

        address_id, road_id, gpkg_geom, plugin_score, plugin_geocoder, plugin_sezioni_censimento = extract_entry_data(
            GeodiffEntryDict.from_entry(entry, geodiff_schema)
        )

        assert address_id == 99001
        assert road_id == 5001
        assert gpkg_geom == "R1AAAQAAAAABAQAAAAAAAICcwitAAAAAwInzREA="
        assert plugin_score == 1.0
        assert plugin_geocoder == "ANNCSU"

    def test_extract_entry_data_with_plugin_score_only(self, geodiff_schema):
        from types import SimpleNamespace

        entry = SimpleNamespace(
            type="update",
            table="addresses",
            changes=[
                Change(column=0, old=99002, new=None),
                Change(column=20, old=None, new="0.8"),
            ],
        )

        address_id, road_id, gpkg_geom, plugin_score, plugin_geocoder, plugin_sezioni_censimento = extract_entry_data(
            GeodiffEntryDict.from_entry(entry, geodiff_schema)
        )

        assert address_id == 99002
        assert plugin_score == 0.8
        assert plugin_geocoder is None

    def test_extract_entry_data_with_plugin_geocoder_only(self, geodiff_schema):
        from types import SimpleNamespace

        entry = SimpleNamespace(
            type="update",
            table="addresses",
            changes=[
                Change(column=0, old=99003, new=None),
                Change(column=21, old=None, new="OTHER"),
            ],
        )

        address_id, road_id, gpkg_geom, plugin_score, plugin_geocoder, plugin_sezioni_censimento = extract_entry_data(
            GeodiffEntryDict.from_entry(entry, geodiff_schema)
        )

        assert address_id == 99003
        assert plugin_score is None
        assert plugin_geocoder == "OTHER"

    def test_extract_entry_data_plugin_score_uses_old_when_new_is_none(self, geodiff_schema):
        from types import SimpleNamespace

        entry = SimpleNamespace(
            type="update",
            table="addresses",
            changes=[
                Change(column=0, old=99004, new=None),
                Change(column=20, old="1.0", new=None),
                Change(column=21, old="ANNCSU", new=None),
            ],
        )

        address_id, road_id, gpkg_geom, plugin_score, plugin_geocoder, plugin_sezioni_censimento = extract_entry_data(
            GeodiffEntryDict.from_entry(entry, geodiff_schema)
        )

        assert plugin_score == 1.0
        assert plugin_geocoder == "ANNCSU"

    def test_extract_entry_data_with_sezioni_censimento(self, geodiff_schema):
        from types import SimpleNamespace

        entry = SimpleNamespace(
            type="update",
            table="addresses",
            changes=[
                Change(column=0, old=99005, new=None),
                Change(column=22, old=None, new="0580910001"),
            ],
        )

        *_, plugin_sezioni_censimento = extract_entry_data(GeodiffEntryDict.from_entry(entry, geodiff_schema))

        assert plugin_sezioni_censimento == "0580910001"


# ============================================================================
# Tests for process_entry function
# ============================================================================


class TestProcessEntry:
    def test_process_entry_update_success(
        self,
        geodiff_schema,
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
            schema=geodiff_schema,
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
        geodiff_schema,
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
            schema=geodiff_schema,
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
        geodiff_schema,
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
            schema=geodiff_schema,
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
        geodiff_schema,
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
            schema=geodiff_schema,
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

    def test_process_entry_delete_not_implemented(
        self,
        geodiff_schema,
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
            schema=geodiff_schema,
            settings=mock_settings,
            cli_runner=mock_cli_runner,
            cli_app=mock_cli_app,
            anncsu_sdk=mock_anncsu_consultazione,
            geodiff=mock_geodiff,
            wkb_loader=mock_wkb_loader,
            logger=mock_logger,
        )

        # Delete is not implemented yet: the entry is reported as failed
        assert result is False
        info_messages = [msg for level, msg in mock_logger.messages if level == "info"]
        assert any("Delete" in msg for msg in info_messages)
        warn_messages = [msg for level, msg in mock_logger.messages if level == "warn"]
        assert any("Delete action is not implemented yet" in msg for msg in warn_messages)

    def test_process_entry_invalid_geometry(
        self,
        geodiff_schema,
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
            schema=geodiff_schema,
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
        geodiff_schema,
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
            schema=geodiff_schema,
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
        geodiff_schema,
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

        mock_change = Change(column=0, old=1001, new=None)
        mock_geom_change = Change(column=1, old=None, new="R1AAAQAAAAABAQAAAAAAAICcwitAAAAAwInzREA=")
        entry = SimpleNamespace(
            type="unknown_action",
            table="addresses",
            changes=[mock_change, mock_geom_change],
        )

        result = process_entry(
            entry=entry,  # type: ignore[arg-type]  # Intentionally bypassing Pydantic validation
            schema=geodiff_schema,
            settings=mock_settings,
            cli_runner=mock_cli_runner,
            cli_app=mock_cli_app,
            anncsu_sdk=mock_anncsu_consultazione,
            geodiff=mock_geodiff,
            wkb_loader=mock_wkb_loader,
            logger=mock_logger,
        )

        # the unknown type is rejected when the entry is mapped to column names
        assert result is False
        assert mock_cli_runner.invocations == []
        error_messages = [msg for level, msg in mock_logger.messages if level == "error"]
        assert any("Invalid geodiff entry" in msg and "type" in msg for msg in error_messages)

    def test_process_entry_anncsu_no_record_found(
        self,
        geodiff_schema,
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
            schema=geodiff_schema,
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
        geodiff_schema,
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
            schema=geodiff_schema,
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
        geodiff_schema,
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
            schema=geodiff_schema,
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
        geodiff_schema,
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
            schema=geodiff_schema,
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
        geodiff_schema,
        mock_settings,
        mock_cli_runner,
        mock_cli_app,
        mock_geodiff,
        mock_wkb_loader,
        mock_logger,
        mock_anncsu_consultazione,
    ):
        """Test insert with negative address_id (new record) without ODONIMO: the road can't be found."""
        from types import SimpleNamespace

        # Create an insert entry with negative address_id
        mock_change_addr = Change(column=0, old=None, new=-1)
        mock_change_geom = Change(column=1, old=None, new="R1AAAQAAAAABAQAAAAAAAICcwitAAAAAwInzREA=")
        mock_change_road = Change(column=4, old=None, new=5001)
        entry = SimpleNamespace(
            type="insert",
            table="addresses",
            changes=[mock_change_addr, mock_change_geom, mock_change_road],
        )

        result = process_entry(
            entry=entry,  # type: ignore[arg-type]
            schema=geodiff_schema,
            settings=mock_settings,
            cli_runner=mock_cli_runner,
            cli_app=mock_cli_app,
            anncsu_sdk=mock_anncsu_consultazione,
            geodiff=mock_geodiff,
            wkb_loader=mock_wkb_loader,
            logger=mock_logger,
        )

        assert result is False
        assert mock_cli_runner.invocations == []
        warn_messages = [msg for level, msg in mock_logger.messages if level == "warn"]
        assert any("not found in ANNCSU; skipping insert for address_id=-1" in msg for msg in warn_messages)

    def test_process_entry_skipped_when_insert_with_plugin_score_1_and_geocoder_anncsu(
        self,
        geodiff_schema,
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
                Change(column=0, old=None, new=50001),
                Change(column=1, old=None, new="R1AAAQAAAAABAQAAAAAAAICcwitAAAAAwInzREA="),
                Change(column=4, old=None, new=9001),
                Change(column=20, old=None, new="1.0"),
                Change(column=21, old=None, new="ANNCSU"),
            ],
        )

        result = process_entry(
            entry=entry,  # type: ignore[arg-type]
            schema=geodiff_schema,
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
        geodiff_schema,
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
                Change(column=0, old=50006, new=None),
                Change(column=1, old=None, new="R1AAAQAAAAABAQAAAAAAAICcwitAAAAAwInzREA="),
                Change(column=4, old=9006, new=None),
                Change(column=20, old=None, new="1.0"),
                Change(column=21, old=None, new="ANNCSU"),
            ],
        )

        result = process_entry(
            entry=entry,  # type: ignore[arg-type]
            schema=geodiff_schema,
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
        geodiff_schema,
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
                Change(column=0, old=50002, new=None),
                Change(column=1, old=None, new="R1AAAQAAAAABAQAAAAAAAICcwitAAAAAwInzREA="),
                Change(column=4, old=9002, new=None),
                Change(column=20, old=None, new="0.5"),
                Change(column=21, old=None, new="ANNCSU"),
            ],
        )

        result = process_entry(
            entry=entry,  # type: ignore[arg-type]
            schema=geodiff_schema,
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
        geodiff_schema,
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
                Change(column=0, old=50003, new=None),
                Change(column=1, old=None, new="R1AAAQAAAAABAQAAAAAAAICcwitAAAAAwInzREA="),
                Change(column=4, old=9003, new=None),
                Change(column=20, old=None, new="1.0"),
                Change(column=21, old=None, new="OTHER_GEOCODER"),
            ],
        )

        result = process_entry(
            entry=entry,  # type: ignore[arg-type]
            schema=geodiff_schema,
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
        geodiff_schema,
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
                Change(column=0, old=50004, new=None),
                Change(column=1, old=None, new="R1AAAQAAAAABAQAAAAAAAICcwitAAAAAwInzREA="),
                Change(column=4, old=9004, new=None),
            ],
        )

        result = process_entry(
            entry=entry,  # type: ignore[arg-type]
            schema=geodiff_schema,
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
        geodiff_schema,
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
                Change(column=0, old=50005, new=None),
                Change(column=1, old=None, new="R1AAAQAAAAABAQAAAAAAAICcwitAAAAAwInzREA="),
                Change(column=4, old=9005, new=None),
                Change(column=20, old=None, new="1.0"),
            ],
        )

        result = process_entry(
            entry=entry,  # type: ignore[arg-type]
            schema=geodiff_schema,
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
        geodiff_schema,
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
            schema=geodiff_schema,
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
        assert results[0].success is True
        assert results[1].success is True
        # delete is not implemented yet
        assert results[2].success is False

    def test_process_all_entries_empty(
        self,
        geodiff_schema,
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
            schema=geodiff_schema,
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
        geodiff_schema,
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
            schema=geodiff_schema,
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
# Tests for load_geodiff_schema function
# ============================================================================


class TestLoadGeodiffSchema:
    def test_load_real_schema_from_text(self, geodiff_real_schema_json, mock_logger):
        schema = load_geodiff_schema(geodiff_real_schema_json, mock_logger)

        assert schema == json.loads(geodiff_real_schema_json)
        info_messages = [msg for level, msg in mock_logger.messages if level == "info"]
        assert any("PROGRESSIVO_NAZIONALE=8" in msg and "ODONIMO=10" in msg for msg in info_messages)

    def test_load_schema_from_file(self, tmp_path, geodiff_real_schema_json, mock_logger):
        schema_file = tmp_path / "schema.json"
        schema_file.write_text(geodiff_real_schema_json)

        assert load_geodiff_schema(str(schema_file), mock_logger) == json.loads(geodiff_real_schema_json)

    def test_missing_column_warns(self, mock_logger):
        schema = '[{"name": "PROGRESSIVO_ACCESSO", "column": 3}]'

        assert load_geodiff_schema(schema, mock_logger) == [{"name": "PROGRESSIVO_ACCESSO", "column": 3}]
        warn_messages = [msg for level, msg in mock_logger.messages if level == "warn"]
        assert any("PLUGIN_SCORE" in msg for msg in warn_messages)
        assert not any("PROGRESSIVO_ACCESSO" in msg for msg in warn_messages)

    def test_invalid_schema(self, mock_logger):
        assert load_geodiff_schema("invalid json", mock_logger) is None
        error_messages = [msg for level, msg in mock_logger.messages if level == "error"]
        assert any("geodiff_schema" in msg for msg in error_messages)

    def test_schema_item_without_name(self, mock_logger):
        assert load_geodiff_schema('[{"column": 0}]', mock_logger) is None

    def test_no_global_state(self, geodiff_real_schema_json, mock_logger):
        load_geodiff_schema(geodiff_real_schema_json, mock_logger)

        assert not any(
            name.startswith("COLUMN_") and not name.startswith("COLUMN_NAME") for name in vars(main_with_cli)
        )


# ============================================================================
# Tests for run_action function
# ============================================================================


class TestRunAction:
    def test_run_action_success(
        self,
        geodiff_schema_json,
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
            geodiff_schema=geodiff_schema_json,
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
        geodiff_schema_json,
        mock_settings,
        mock_cli_runner,
        mock_cli_app,
        mock_geodiff,
        mock_wkb_loader,
        mock_logger,
    ):
        result = run_action(
            geodiff_report="invalid json",
            geodiff_schema=geodiff_schema_json,
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
        geodiff_schema_json,
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
            geodiff_schema=geodiff_schema_json,
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
        geodiff_schema_json,
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
            geodiff_schema=geodiff_schema_json,
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
        geodiff_schema_json,
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
            geodiff_schema=geodiff_schema_json,
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
        geodiff_schema_json,
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
            geodiff_schema=geodiff_schema_json,
            settings=mock_settings,
            cli_runner=mock_cli_runner,
            cli_app=mock_cli_app,
            geodiff=mock_geodiff,
            wkb_loader=mock_wkb_loader,
            logger=mock_logger,
            token="test-token",
        )

        assert result is True  # Empty is success (nothing to do)


# ============================================================================
# Tests for query_anncsu_road
# ============================================================================


def _roads_result(*roads):
    return MockCliResult(exit_code=0, output=json.dumps(list(roads)))


class TestQueryAnncsuRoad:
    def test_single_road_returned(self, mock_cli_app, mock_logger):
        road = {"prognaz": "907000", "dug": "VIA", "denomuff": "ROMA"}
        runner = MockCliRunner(result=_roads_result(road))

        result = main_with_cli.query_anncsu_road("VIA ROMA", "I501", runner, mock_cli_app, mock_logger)

        assert result == road

    def test_builds_odonimo_command_with_base64_denom(self, mock_cli_app, mock_logger):
        runner = MockCliRunner(result=_roads_result({"prognaz": "1", "dug": "VIA", "denomuff": "ROMA"}))

        main_with_cli.query_anncsu_road("  VIA ROMA ", "I501", runner, mock_cli_app, mock_logger)

        _, args = runner.invocations[0]
        assert args[:2] == ["pa", "odonimo"]
        assert args[args.index("--codcom") + 1] == "I501"
        assert base64.b64decode(args[args.index("--denom") + 1]).decode("utf-8") == "VIA ROMA"
        assert "--production" in args
        assert args[args.index("--token-endpoint") + 1] == main_with_cli.TOKEN_ENDPOINT
        assert "--json" in args

    def test_non_ascii_odonimo_is_encoded(self, mock_cli_app, mock_logger):
        runner = MockCliRunner(result=_roads_result({"prognaz": "1", "dug": "VIA", "denomuff": "SANT'ANDREA ÀÈ"}))

        main_with_cli.query_anncsu_road("VIA SANT'ANDREA ÀÈ", "I501", runner, mock_cli_app, mock_logger)

        _, args = runner.invocations[0]
        assert base64.b64decode(args[args.index("--denom") + 1]).decode("utf-8") == "VIA SANT'ANDREA ÀÈ"

    def test_cli_failure_returns_none(self, mock_cli_app, mock_logger):
        runner = MockCliRunner(result=MockCliResult(exit_code=1, output="No odonimo found"))

        result = main_with_cli.query_anncsu_road("VIA ROMA", "I501", runner, mock_cli_app, mock_logger)

        assert result is None
        assert any(level == "warn" and "No ANNCSU road found" in msg for level, msg in mock_logger.messages)

    def test_empty_result_returns_none(self, mock_cli_app, mock_logger):
        runner = MockCliRunner(result=_roads_result())

        assert main_with_cli.query_anncsu_road("VIA ROMA", "I501", runner, mock_cli_app, mock_logger) is None

    @pytest.mark.parametrize("odonimo", ["", "   ", None])
    def test_empty_odonimo_skips_cli(self, mock_cli_app, mock_logger, odonimo):
        runner = MockCliRunner()

        assert main_with_cli.query_anncsu_road(odonimo, "I501", runner, mock_cli_app, mock_logger) is None
        assert runner.invocations == []

    @pytest.mark.parametrize("odonimo", ["VIA ROMA", "via roma", "ROMA"])
    def test_multiple_roads_selects_exact_match(self, mock_cli_app, mock_logger, odonimo):
        roma = {"prognaz": "1", "dug": "VIA", "denomuff": "ROMA"}
        runner = MockCliRunner(
            result=_roads_result(
                roma,
                {"prognaz": "2", "dug": "VIA", "denomuff": "ROMA ANTICA"},
                {"prognaz": "3", "dug": "PIAZZA", "denomuff": "ROMANA"},
            )
        )

        result = main_with_cli.query_anncsu_road(odonimo, "I501", runner, mock_cli_app, mock_logger)

        assert result == roma

    def test_multiple_roads_without_exact_match_returns_none(self, mock_cli_app, mock_logger):
        runner = MockCliRunner(
            result=_roads_result(
                {"prognaz": "2", "dug": "VIA", "denomuff": "ROMA ANTICA"},
                {"prognaz": "3", "dug": "PIAZZA", "denomuff": "ROMANA"},
            )
        )

        assert main_with_cli.query_anncsu_road("VIA ROMA", "I501", runner, mock_cli_app, mock_logger) is None

    def test_multiple_exact_matches_returns_none(self, mock_cli_app, mock_logger):
        # "ROMA" matches both roads by denomuff only
        runner = MockCliRunner(
            result=_roads_result(
                {"prognaz": "1", "dug": "VIA", "denomuff": "ROMA"},
                {"prognaz": "2", "dug": "PIAZZA", "denomuff": "ROMA"},
            )
        )

        assert main_with_cli.query_anncsu_road("ROMA", "I501", runner, mock_cli_app, mock_logger) is None

    def test_road_with_missing_fields(self, mock_cli_app, mock_logger):
        road = {"prognaz": "1", "dug": None, "denomuff": "ROMA"}
        runner = MockCliRunner(result=_roads_result(road, {"prognaz": "2", "dug": None, "denomuff": None}))

        assert main_with_cli.query_anncsu_road("ROMA", "I501", runner, mock_cli_app, mock_logger) == road

    def test_dry_run_runner_returns_searched_road(self, mock_cli_app, mock_logger):
        runner = main_with_cli.DryRunCliRunner(mock_logger)

        result = main_with_cli.query_anncsu_road("VIA ROMA", "I501", runner, mock_cli_app, mock_logger)

        assert result == {"prognaz": "0", "dug": None, "denomuff": "VIA ROMA"}


# ============================================================================
# Tests for extract_odonimo and insert road check
# ============================================================================


def _insert_entry(*changes):
    return GeodiffFile.from_json_text(
        json.dumps({"geodiff": [{"table": "civici", "type": "insert", "changes": list(changes)}]})
    ).geodiff[0]


def _insert(entry, schema, address_id, settings, runner, cli_app, logger):
    entry_dict = GeodiffEntryDict.from_entry(entry, schema)
    return main_with_cli.insert_address(entry_dict, address_id, 13.0, 42.0, settings, runner, cli_app, logger)


class TestExtractOdonimo:
    def test_extract_new_value(self, geodiff_schema):
        entry = _insert_entry({"column": 0, "new": 1}, {"column": 3, "new": "VIA ROMA"})

        assert main_with_cli.extract_odonimo(GeodiffEntryDict.from_entry(entry, geodiff_schema)) == "VIA ROMA"

    def test_extract_old_value(self, geodiff_schema):
        entry = _insert_entry({"column": 3, "old": "VIA ROMA"})

        assert main_with_cli.extract_odonimo(GeodiffEntryDict.from_entry(entry, geodiff_schema)) == "VIA ROMA"

    def test_missing_column_returns_none(self, geodiff_schema):
        entry = _insert_entry({"column": 0, "new": 1})

        assert main_with_cli.extract_odonimo(GeodiffEntryDict.from_entry(entry, geodiff_schema)) is None

    def test_uses_schema_column(self, geodiff_real_schema_json):
        # in the real schema column 3 is PLUGIN_COMUNE and ODONIMO is column 10
        entry = _insert_entry({"column": 3, "new": "not the road"}, {"column": 10, "new": "VIA ROMA"})

        entry_dict = GeodiffEntryDict.from_entry(entry, json.loads(geodiff_real_schema_json))

        assert main_with_cli.extract_odonimo(entry_dict) == "VIA ROMA"


class TestExtractEntryDataBySchema:
    def test_same_values_with_different_layouts(self, geodiff_schema, geodiff_real_schema_json):
        test_layout = _insert_entry(
            {"column": 0, "new": 7},
            {"column": 1, "new": "R1AAAQ=="},
            {"column": 4, "new": 501},
            {"column": 20, "new": 0.5},
            {"column": 21, "new": "NOMINATIM"},
        )
        real_layout = _insert_entry(
            {"column": 0, "new": 7},
            {"column": 1, "new": "R1AAAQ=="},
            {"column": 8, "new": 501},
            {"column": 24, "new": 0.5},
            {"column": 25, "new": "NOMINATIM"},
        )

        test_layout.changes.append(Change(column=22, new="0580910001"))
        real_layout.changes.append(Change(column=26, new="0580910001"))

        expected = (7, 501, "R1AAAQ==", 0.5, "NOMINATIM", "0580910001")
        assert extract_entry_data(GeodiffEntryDict.from_entry(test_layout, geodiff_schema)) == expected
        real_schema = json.loads(geodiff_real_schema_json)
        assert extract_entry_data(GeodiffEntryDict.from_entry(real_layout, real_schema)) == expected

    def test_zero_new_value_is_not_replaced_by_old(self, geodiff_schema):
        entry = GeodiffFile.from_json_text(
            json.dumps(
                {
                    "geodiff": [
                        {
                            "table": "civici",
                            "type": "update",
                            "changes": [{"column": 0, "old": 7}, {"column": 20, "old": 1.0, "new": 0.0}],
                        }
                    ]
                }
            )
        ).geodiff[0]

        _, _, _, plugin_score, _, _ = extract_entry_data(GeodiffEntryDict.from_entry(entry, geodiff_schema))

        assert plugin_score == 0.0


class TestProcessEntrySchemaMismatch:
    def test_unknown_column_skips_entry(
        self,
        geodiff_schema,
        mock_settings,
        mock_cli_runner,
        mock_cli_app,
        mock_geodiff,
        mock_wkb_loader,
        mock_logger,
        mock_anncsu_consultazione,
    ):
        entry = _insert_entry({"column": 0, "new": 42}, {"column": 99, "new": "?"})

        result = process_entry(
            entry=entry,
            schema=geodiff_schema,
            settings=mock_settings,
            cli_runner=mock_cli_runner,
            cli_app=mock_cli_app,
            anncsu_sdk=mock_anncsu_consultazione,
            geodiff=mock_geodiff,
            wkb_loader=mock_wkb_loader,
            logger=mock_logger,
        )

        assert result is False
        assert mock_cli_runner.invocations == []
        error_messages = [msg for level, msg in mock_logger.messages if level == "error"]
        assert any("Invalid geodiff entry" in msg and "Column 99" in msg for msg in error_messages)


class TestProcessEntrySezioniCensimento:
    """Update entries of records never inserted in ANNCSU (negative ids) carrying
    PLUGIN_SEZIONI_CENSIMENTO are inserted instead of updated."""

    GEOM = "R1AAAQAAAAABAQAAAAAAAICcwitAAAAAwInzREA="

    def _process(self, changes, schema, settings, runner, cli_app, geodiff, wkb_loader, logger, anncsu_sdk):
        from types import SimpleNamespace

        entry = SimpleNamespace(type="update", table="civici", changes=[Change(**c) for c in changes])
        return process_entry(
            entry=entry,  # type: ignore[arg-type]
            schema=schema,
            settings=settings,
            cli_runner=runner,
            cli_app=cli_app,
            anncsu_sdk=anncsu_sdk,
            geodiff=geodiff,
            wkb_loader=wkb_loader,
            logger=logger,
        )

    def test_update_with_sezioni_and_negative_ids_inserts(
        self,
        geodiff_schema,
        mock_settings,
        mock_cli_runner,
        mock_cli_app,
        mock_geodiff,
        mock_wkb_loader,
        mock_logger,
        mock_anncsu_consultazione,
    ):
        changes = [
            {"column": 0, "old": -42},
            {"column": 1, "new": self.GEOM},
            {"column": 3, "old": "VIA ROMA"},
            {"column": 4, "old": -7},
            {"column": 5, "old": 12},
            {"column": 22, "old": None, "new": "0580910001"},
        ]

        result = self._process(
            changes,
            geodiff_schema,
            mock_settings,
            mock_cli_runner,
            mock_cli_app,
            mock_geodiff,
            mock_wkb_loader,
            mock_logger,
            mock_anncsu_consultazione,
        )

        assert result is True
        commands = [args for _, args in mock_cli_runner.invocations]
        assert [c[:2] for c in commands] == [["pa", "odonimo"], ["accesso", "insert"]]
        insert = commands[1]
        assert insert[insert.index("--sezione-censimento") + 1] == "0580910001"

    @pytest.mark.parametrize(
        "changes",
        [
            # no PLUGIN_SEZIONI_CENSIMENTO
            [{"column": 0, "old": -42}, {"column": 4, "old": -7}],
            # positive address_id: record already in ANNCSU
            [{"column": 0, "old": 42}, {"column": 4, "old": -7}, {"column": 22, "new": "0580910001"}],
            # positive road_id
            [{"column": 0, "old": -42}, {"column": 4, "old": 7}, {"column": 22, "new": "0580910001"}],
            # road_id not in the changes
            [{"column": 0, "old": -42}, {"column": 22, "new": "0580910001"}],
        ],
    )
    def test_update_without_special_case_updates_coordinates(
        self,
        geodiff_schema,
        mock_settings,
        mock_cli_runner,
        mock_cli_app,
        mock_geodiff,
        mock_wkb_loader,
        mock_logger,
        mock_anncsu_consultazione,
        changes,
    ):
        self._process(
            [*changes, {"column": 1, "new": self.GEOM}],
            geodiff_schema,
            mock_settings,
            mock_cli_runner,
            mock_cli_app,
            mock_geodiff,
            mock_wkb_loader,
            mock_logger,
            mock_anncsu_consultazione,
        )

        commands = [args[:2] for _, args in mock_cli_runner.invocations]
        assert ["accesso", "insert"] not in commands
        assert ["pa", "odonimo"] not in commands


class TestUpdateCoordinates:
    def _entry_dict(self, schema, entry_type="update"):
        entry = GeodiffFile.from_json_text(
            json.dumps(
                {
                    "geodiff": [
                        {
                            "table": "civici",
                            "type": entry_type,
                            "changes": [{"column": 0, "old": 42}, {"column": 1, "new": "R1AAAQ=="}],
                        }
                    ]
                }
            )
        ).geodiff[0]
        return GeodiffEntryDict.from_entry(entry, schema)

    def test_updates_changed_coordinates(
        self, geodiff_schema, mock_settings, mock_cli_runner, mock_cli_app, mock_logger
    ):
        entry_dict = self._entry_dict(geodiff_schema)

        result = main_with_cli.update_coordinates(
            entry_dict, 42, 13.0, 42.0, mock_settings, mock_cli_runner, mock_cli_app, mock_logger
        )

        assert result is True
        commands = [args for _, args in mock_cli_runner.invocations]
        assert [c[:2] for c in commands] == [["pa", "accesso"], ["coordinate", "update"]]
        update = commands[1]
        assert update[update.index("--progr-civico") + 1] == "42"
        assert update[update.index("--x") + 1] == "13.000000000"
        assert update[update.index("--y") + 1] == "42.000000000"

    def test_logs_entry_type_table_and_changes(
        self, geodiff_schema, mock_settings, mock_cli_runner, mock_cli_app, mock_logger
    ):
        entry_dict = self._entry_dict(geodiff_schema, entry_type="insert")

        main_with_cli.update_coordinates(
            entry_dict, 42, 13.0, 42.0, mock_settings, mock_cli_runner, mock_cli_app, mock_logger
        )

        info_messages = [msg for level, msg in mock_logger.messages if level == "info"]
        assert "insert 2 column values in civici with PK: address_id=42" in info_messages

    def test_same_coordinates_skip_update(self, geodiff_schema, mock_settings, mock_cli_app, mock_logger):
        runner = MockCliRunner(query_result=MockCliResult(exit_code=0, output='[{"coordX": 13.0, "coordY": 42.0}]'))

        result = main_with_cli.update_coordinates(
            self._entry_dict(geodiff_schema), 42, 13.0, 42.0, mock_settings, runner, mock_cli_app, mock_logger
        )

        assert result is True
        assert [args[:2] for _, args in runner.invocations] == [["pa", "accesso"]]

    def test_record_not_found(self, geodiff_schema, mock_settings, mock_cli_app, mock_logger):
        runner = MockCliRunner(query_result=MockCliResult(exit_code=0, output="[]"))

        result = main_with_cli.update_coordinates(
            self._entry_dict(geodiff_schema), 42, 13.0, 42.0, mock_settings, runner, mock_cli_app, mock_logger
        )

        assert result is False
        assert [args[:2] for _, args in runner.invocations] == [["pa", "accesso"]]

    def test_update_command_failure(self, geodiff_schema, mock_settings, mock_cli_app, mock_logger):
        runner = MockCliRunner(
            query_result=MockCliResult(exit_code=0, output='[{"coordX": 10.0, "coordY": 50.0}]'),
            result=MockCliResult(exit_code=1, output="boom"),
        )

        result = main_with_cli.update_coordinates(
            self._entry_dict(geodiff_schema), 42, 13.0, 42.0, mock_settings, runner, mock_cli_app, mock_logger
        )

        assert result is False
        error_messages = [msg for level, msg in mock_logger.messages if level == "error"]
        assert any("coordinate update failed" in msg for msg in error_messages)


class TestDeleteAddress:
    def test_delete_not_implemented(
        self, geodiff_schema, geodiff_delete_json, mock_settings, mock_cli_runner, mock_cli_app, mock_logger
    ):
        entry = GeodiffFile.from_json_text(geodiff_delete_json).geodiff[0]
        entry_dict = GeodiffEntryDict.from_entry(entry, geodiff_schema)

        result = main_with_cli.delete_address(entry_dict, 2, mock_settings, mock_cli_runner, mock_cli_app, mock_logger)

        assert result is False
        assert mock_cli_runner.invocations == []
        info_messages = [msg for level, msg in mock_logger.messages if level == "info"]
        assert "Delete 4 values from simple with PK: address_id=2" in info_messages
        warn_messages = [msg for level, msg in mock_logger.messages if level == "warn"]
        assert any("Delete action is not implemented yet" in msg for msg in warn_messages)


class TestInsertAddress:
    def test_queries_road_then_inserts_accesso(
        self, geodiff_schema, mock_settings, mock_cli_runner, mock_cli_app, mock_logger
    ):
        entry = _insert_entry({"column": 0, "new": -42}, {"column": 3, "new": "VIA ROMA"}, {"column": 5, "new": 12})

        result = _insert(entry, geodiff_schema, -42, mock_settings, mock_cli_runner, mock_cli_app, mock_logger)

        assert result is True
        commands = [args for _, args in mock_cli_runner.invocations]
        assert [c[:2] for c in commands] == [["pa", "odonimo"], ["accesso", "insert"]]
        road_query = commands[0]
        assert road_query[road_query.index("--codcom") + 1] == mock_settings.codice_comune
        assert base64.b64decode(road_query[road_query.index("--denom") + 1]).decode("utf-8") == "VIA ROMA"

    def test_road_not_found_skips_update(self, geodiff_schema, mock_settings, mock_cli_app, mock_logger):
        runner = MockCliRunner(
            query_result=MockCliResult(exit_code=0, output='[{"coordX": 10.0, "coordY": 50.0}]'),
            odonimo_result=MockCliResult(exit_code=1, output="No odonimo found"),
        )
        entry = _insert_entry({"column": 0, "new": -42}, {"column": 3, "new": "VIA INESISTENTE"})

        result = _insert(entry, geodiff_schema, -42, mock_settings, runner, mock_cli_app, mock_logger)

        assert result is False
        assert [args[:2] for _, args in runner.invocations] == [["pa", "odonimo"]]
        warn_messages = [msg for level, msg in mock_logger.messages if level == "warn"]
        assert any("not found in ANNCSU; skipping insert" in msg for msg in warn_messages)

    def test_missing_odonimo_skips_cli(
        self, geodiff_schema, mock_settings, mock_cli_runner, mock_cli_app, mock_logger
    ):
        entry = _insert_entry({"column": 0, "new": -42})

        result = _insert(entry, geodiff_schema, -42, mock_settings, mock_cli_runner, mock_cli_app, mock_logger)

        assert result is False
        assert mock_cli_runner.invocations == []

    def test_positive_address_id_skips_insert(
        self, geodiff_schema, mock_settings, mock_cli_runner, mock_cli_app, mock_logger
    ):
        # a positive address_id is an existing ANNCSU record: it should be an update, not an insert
        entry = _insert_entry({"column": 0, "new": 42}, {"column": 3, "new": "VIA ROMA"}, {"column": 5, "new": 12})

        result = _insert(entry, geodiff_schema, 42, mock_settings, mock_cli_runner, mock_cli_app, mock_logger)

        assert result is False
        assert mock_cli_runner.invocations == []
        warn_messages = [msg for level, msg in mock_logger.messages if level == "warn"]
        assert any("existing record should be an update" in msg for msg in warn_messages)

    def test_invalid_road_query_output(self, geodiff_schema, mock_settings, mock_cli_app, mock_logger):
        runner = MockCliRunner(odonimo_result=MockCliResult(exit_code=0, output="not json"))
        entry = _insert_entry({"column": 0, "new": -42}, {"column": 3, "new": "VIA ROMA"})

        result = _insert(entry, geodiff_schema, -42, mock_settings, runner, mock_cli_app, mock_logger)

        assert result is False
        error_messages = [msg for level, msg in mock_logger.messages if level == "error"]
        assert any("Invalid ANNCSU road query output" in msg for msg in error_messages)

    def test_dry_run_insert_logs_road_query(self, geodiff_schema, mock_settings, mock_cli_app, mock_logger):
        runner = main_with_cli.DryRunCliRunner(mock_logger)
        entry = _insert_entry({"column": 0, "new": -42}, {"column": 3, "new": "VIA ROMA"}, {"column": 5, "new": 12})

        result = _insert(entry, geodiff_schema, -42, mock_settings, runner, mock_cli_app, mock_logger)

        assert result is True
        assert [c[:2] for c in runner.calls] == [["pa", "odonimo"], ["accesso", "insert"]]


class TestInsertAccessoCommand:
    """Tests for the "accesso insert" CLI command built from the entry (real schema layout)."""

    ROAD = {"prognaz": "2000449", "dug": "VIA", "denomuff": "ROMA"}

    def _run(self, schema_json, changes, settings, cli_app, logger, road=None, insert_result=None):
        runner = MockCliRunner(
            odonimo_result=MockCliResult(exit_code=0, output=json.dumps([road or self.ROAD])),
            result=insert_result or MockCliResult(exit_code=0, output='{"esito": "OK"}'),
        )
        entry = _insert_entry({"column": 0, "new": -42}, {"column": 10, "new": "VIA ROMA"}, *changes)
        result = _insert(entry, json.loads(schema_json), -42, settings, runner, cli_app, logger)
        inserts = [args for _, args in runner.invocations if args[:2] == ["accesso", "insert"]]
        return result, inserts

    @staticmethod
    def _opts(args):
        """Map each --option to its value (flags without a value map to True)."""
        opts = {}
        i = 2
        while i < len(args):
            if i + 1 < len(args) and not args[i + 1].startswith("--"):
                opts[args[i]] = args[i + 1]
                i += 2
            else:
                opts[args[i]] = True
                i += 1
        return opts

    def test_all_values_from_entry(self, geodiff_real_schema_json, mock_settings, mock_cli_app, mock_logger):
        changes = [
            {"column": 6, "new": "A062"},  # CODICE_COMUNE
            {"column": 8, "new": 111},  # PROGRESSIVO_NAZIONALE: ignored, prognaz comes from the road
            {"column": 14, "new": "CC-1"},  # CODICE_COMUNALE_ACCESSO
            {"column": 15, "new": 12},  # CIVICO
            {"column": 16, "new": "BIS"},  # ESPONENTE
            {"column": 17, "new": "ROSSO"},  # SPECIFICITA
            {"column": 22, "new": 120.5},  # QUOTA
            {"column": 23, "new": 2},  # METODO
            {"column": 26, "new": "0580910001"},  # PLUGIN_SEZIONI_CENSIMENTO
        ]

        result, inserts = self._run(geodiff_real_schema_json, changes, mock_settings, mock_cli_app, mock_logger)

        assert result is True
        assert len(inserts) == 1
        opts = self._opts(inserts[0])
        assert opts == {
            "--production": True,
            "--codcom": "A062",
            "--prognaz": "2000449",
            "--sezione-censimento": "0580910001",
            "--numero": "12",
            "--esponente": "BIS",
            "--specificita": "ROSSO",
            "--codice-civico-comunale": "CC-1",
            "--coord-x": "13.000000000",
            "--coord-y": "42.000000000",
            "--coord-z": "120.5",
            "--metodo": "2",
            "--token-endpoint": main_with_cli.TOKEN_ENDPOINT,
            "--json": True,
        }

    def test_metrico_instead_of_numero(self, geodiff_real_schema_json, mock_settings, mock_cli_app, mock_logger):
        changes = [{"column": 8, "new": 2000449}, {"column": 18, "new": 350}]  # METRICO

        result, inserts = self._run(geodiff_real_schema_json, changes, mock_settings, mock_cli_app, mock_logger)

        assert result is True
        opts = self._opts(inserts[0])
        assert opts["--metrico"] == "350"
        assert "--numero" not in opts

    def test_missing_optional_values_are_omitted(
        self, geodiff_real_schema_json, mock_settings, mock_cli_app, mock_logger
    ):
        changes = [{"column": 8, "new": 2000449}, {"column": 15, "new": 12}, {"column": 16, "new": ""}]

        _, inserts = self._run(geodiff_real_schema_json, changes, mock_settings, mock_cli_app, mock_logger)

        opts = self._opts(inserts[0])
        for option in ("--esponente", "--specificita", "--codice-civico-comunale", "--coord-z", "--metrico"):
            assert option not in opts
        assert opts["--metodo"] == main_with_cli.DEFAULT_METODO

    def test_integral_float_civico_has_no_decimals(
        self, geodiff_real_schema_json, mock_settings, mock_cli_app, mock_logger
    ):
        changes = [{"column": 8, "new": 2000449}, {"column": 15, "new": 12.0}]

        _, inserts = self._run(geodiff_real_schema_json, changes, mock_settings, mock_cli_app, mock_logger)

        assert self._opts(inserts[0])["--numero"] == "12"

    def test_missing_sezione_censimento_defaults_to_9999(
        self, geodiff_real_schema_json, mock_settings, mock_cli_app, mock_logger
    ):
        changes = [{"column": 15, "new": 12}]

        result, inserts = self._run(geodiff_real_schema_json, changes, mock_settings, mock_cli_app, mock_logger)

        assert result is True
        assert self._opts(inserts[0])["--sezione-censimento"] == "9999"
        warn_messages = [msg for level, msg in mock_logger.messages if level == "warn"]
        assert any("No sezione censimento provided" in msg and "address_id=-42" in msg for msg in warn_messages)

    def test_codcom_falls_back_to_settings(self, geodiff_real_schema_json, mock_settings, mock_cli_app, mock_logger):
        changes = [{"column": 8, "new": 2000449}, {"column": 15, "new": 12}]

        _, inserts = self._run(geodiff_real_schema_json, changes, mock_settings, mock_cli_app, mock_logger)

        assert self._opts(inserts[0])["--codcom"] == mock_settings.codice_comune

    def test_prognaz_from_road(self, geodiff_real_schema_json, mock_settings, mock_cli_app, mock_logger):
        changes = [{"column": 15, "new": 12}]

        _, inserts = self._run(geodiff_real_schema_json, changes, mock_settings, mock_cli_app, mock_logger)

        assert self._opts(inserts[0])["--prognaz"] == "2000449"

    def test_entry_prognaz_is_ignored(self, geodiff_real_schema_json, mock_settings, mock_cli_app, mock_logger):
        changes = [{"column": 8, "new": 111}, {"column": 15, "new": 12}]

        _, inserts = self._run(geodiff_real_schema_json, changes, mock_settings, mock_cli_app, mock_logger)

        assert self._opts(inserts[0])["--prognaz"] == "2000449"

    def test_road_without_prognaz_skips_insert(
        self, geodiff_real_schema_json, mock_settings, mock_cli_app, mock_logger
    ):
        changes = [{"column": 15, "new": 12}]
        road = {"prognaz": None, "dug": "VIA", "denomuff": "ROMA"}

        result, inserts = self._run(
            geodiff_real_schema_json, changes, mock_settings, mock_cli_app, mock_logger, road=road
        )

        assert result is False
        assert inserts == []

    @pytest.mark.parametrize(
        "changes",
        [
            [{"column": 8, "new": 2000449}],  # neither CIVICO nor METRICO
            [{"column": 8, "new": 2000449}, {"column": 15, "new": 12}, {"column": 18, "new": 350}],  # both
        ],
    )
    def test_numero_xor_metrico_required(
        self, geodiff_real_schema_json, mock_settings, mock_cli_app, mock_logger, changes
    ):
        result, inserts = self._run(geodiff_real_schema_json, changes, mock_settings, mock_cli_app, mock_logger)

        assert result is False
        assert inserts == []
        warn_messages = [msg for level, msg in mock_logger.messages if level == "warn"]
        assert any("Exactly one of CIVICO" in msg for msg in warn_messages)

    def test_dry_run_setting_skips_insert(self, geodiff_real_schema_json, mock_settings, mock_cli_app, mock_logger):
        mock_settings.dry_run = True
        changes = [{"column": 8, "new": 2000449}, {"column": 15, "new": 12}]

        result, inserts = self._run(geodiff_real_schema_json, changes, mock_settings, mock_cli_app, mock_logger)

        # road lookup still runs, the insert is only logged
        assert result is True
        assert inserts == []
        info_messages = [msg for level, msg in mock_logger.messages if level == "info"]
        dry_run_logs = [msg for msg in info_messages if msg.startswith("[DRY RUN] would insert ANNCSU accesso")]
        assert len(dry_run_logs) == 1
        assert "address_id=-42" in dry_run_logs[0]
        assert "accesso insert --production --codcom I501 --prognaz 2000449 --sezione-censimento 9999 --numero 12" in dry_run_logs[0]

    def test_dry_run_setting_skips_insert_even_if_it_would_fail(
        self, geodiff_real_schema_json, mock_settings, mock_cli_app, mock_logger
    ):
        mock_settings.dry_run = True
        changes = [{"column": 8, "new": 2000449}, {"column": 15, "new": 12}]

        result, inserts = self._run(
            geodiff_real_schema_json,
            changes,
            mock_settings,
            mock_cli_app,
            mock_logger,
            insert_result=MockCliResult(exit_code=1, output="rejected"),
        )

        assert result is True
        assert inserts == []

    def test_dry_run_setting_still_validates_entry(
        self, geodiff_real_schema_json, mock_settings, mock_cli_app, mock_logger
    ):
        mock_settings.dry_run = True
        changes = [{"column": 8, "new": 2000449}]  # neither CIVICO nor METRICO

        result, inserts = self._run(geodiff_real_schema_json, changes, mock_settings, mock_cli_app, mock_logger)

        assert result is False
        assert not any("[DRY RUN]" in msg for _, msg in mock_logger.messages)

    def test_insert_failure(self, geodiff_real_schema_json, mock_settings, mock_cli_app, mock_logger):
        changes = [{"column": 8, "new": 2000449}, {"column": 15, "new": 12}]

        result, inserts = self._run(
            geodiff_real_schema_json,
            changes,
            mock_settings,
            mock_cli_app,
            mock_logger,
            insert_result=MockCliResult(exit_code=1, output="rejected"),
        )

        assert result is False
        assert len(inserts) == 1
        error_messages = [msg for level, msg in mock_logger.messages if level == "error"]
        assert any("accesso insert failed: rejected" in msg for msg in error_messages)


# ============================================================================
# Tests for dry run mode
# ============================================================================


class TestDryRun:
    def test_dry_run_cli_runner_query_returns_record_without_coords(self, mock_logger):
        runner = main_with_cli.DryRunCliRunner(mock_logger)

        result = runner.invoke(None, ["pa", "accesso", "--prognazacc", "123", "--json"])

        assert result.exit_code == 0
        assert json.loads(result.output) == [{"prognazacc": "123", "coordX": None, "coordY": None}]
        assert runner.calls == [["pa", "accesso", "--prognazacc", "123", "--json"]]

    def test_dry_run_cli_runner_other_commands_succeed(self, mock_logger):
        runner = main_with_cli.DryRunCliRunner(mock_logger)

        result = runner.invoke(None, ["coordinate", "update", "--x", "1.0"])

        assert result.exit_code == 0
        assert json.loads(result.output) == {"dry_run": True}

    def test_run_action_dry_run_skips_auth_and_cli(
        self,
        geodiff_schema_json,
        geodiff_real_coord_update_json,
        mock_settings,
        mock_cli_runner,
        mock_cli_app,
        mock_geodiff,
        mock_wkb_loader,
        mock_logger,
        monkeypatch,
    ):
        def _fail(*args, **kwargs):
            raise AssertionError("SDK must not be instantiated in dry run")

        monkeypatch.setattr("main_with_cli.AnncsuConsultazione.__init__", _fail)

        result = run_action(
            geodiff_report=geodiff_real_coord_update_json,
            geodiff_schema=geodiff_schema_json,
            settings=mock_settings,
            cli_runner=mock_cli_runner,
            cli_app=mock_cli_app,
            geodiff=mock_geodiff,
            wkb_loader=mock_wkb_loader,
            logger=mock_logger,
            token="test-token",
            dry_run=True,
        )

        assert result is True
        # the real runner is never used: no auth, no query, no update
        assert mock_cli_runner.invocations == []

    @pytest.fixture
    def captured_dry_runners(self, monkeypatch):
        """Capture DryRunCliRunner instances created inside run_action."""
        instances = []
        original = main_with_cli.DryRunCliRunner

        class TrackingDryRunCliRunner(original):
            def __init__(self, logger):
                super().__init__(logger)
                instances.append(self)

        monkeypatch.setattr("main_with_cli.DryRunCliRunner", TrackingDryRunCliRunner)
        return instances

    def _run_dry(self, report, schema, settings, cli_runner, cli_app, geodiff, wkb_loader, logger):
        return run_action(
            geodiff_report=report,
            geodiff_schema=schema,
            settings=settings,
            cli_runner=cli_runner,
            cli_app=cli_app,
            geodiff=geodiff,
            wkb_loader=wkb_loader,
            logger=logger,
            token="test-token",
            dry_run=True,
        )

    def test_dry_run_cli_runner_logs_command(self, mock_logger):
        runner = main_with_cli.DryRunCliRunner(mock_logger)

        runner.invoke(None, ["coordinate", "update", "--x", "1.0"])

        assert ("info", "[DRY RUN] would invoke ANNCSU CLI: coordinate update --x 1.0") in mock_logger.messages

    def test_dry_run_cli_runner_query_without_prognazacc(self, mock_logger):
        runner = main_with_cli.DryRunCliRunner(mock_logger)

        result = runner.invoke(None, ["pa", "accesso", "--json"])

        assert result.exit_code == 0
        assert json.loads(result.output) == [{"prognazacc": "", "coordX": None, "coordY": None}]

    def test_dry_run_cli_runner_satisfies_protocol(self, mock_logger):
        assert isinstance(main_with_cli.DryRunCliRunner(mock_logger), main_with_cli.CliRunnerProtocol)

    def test_run_action_dry_run_logs_query_and_update_commands(
        self,
        geodiff_schema_json,
        geodiff_real_coord_update_json,
        mock_settings,
        mock_cli_runner,
        mock_cli_app,
        mock_geodiff,
        mock_wkb_loader,
        mock_logger,
        captured_dry_runners,
    ):
        result = self._run_dry(
            geodiff_real_coord_update_json,
            geodiff_schema_json,
            mock_settings,
            mock_cli_runner,
            mock_cli_app,
            mock_geodiff,
            mock_wkb_loader,
            mock_logger,
        )

        assert result is True
        assert len(captured_dry_runners) == 1
        calls = captured_dry_runners[0].calls
        # no auth login, only the query and the coordinate update
        assert [c[:2] for c in calls] == [["pa", "accesso"], ["coordinate", "update"]]
        query, update = calls
        assert query[query.index("--prognazacc") + 1] == "28671616"
        assert update[update.index("--progr-civico") + 1] == "28671616"
        assert update[update.index("--codcom") + 1] == mock_settings.codice_comune

    def test_run_action_dry_run_logs_warning(
        self,
        geodiff_schema_json,
        geodiff_real_coord_update_json,
        mock_settings,
        mock_cli_runner,
        mock_cli_app,
        mock_geodiff,
        mock_wkb_loader,
        mock_logger,
    ):
        self._run_dry(
            geodiff_real_coord_update_json,
            geodiff_schema_json,
            mock_settings,
            mock_cli_runner,
            mock_cli_app,
            mock_geodiff,
            mock_wkb_loader,
            mock_logger,
        )

        warnings = [msg for level, msg in mock_logger.messages if level == "warn"]
        assert any("[DRY RUN] enabled" in msg for msg in warnings)
        assert not any("Authenticating" in msg for _, msg in mock_logger.messages)

    def test_run_action_dry_run_does_not_create_security(
        self,
        geodiff_schema_json,
        geodiff_real_coord_update_json,
        mock_settings,
        mock_cli_runner,
        mock_cli_app,
        mock_geodiff,
        mock_wkb_loader,
        mock_logger,
        monkeypatch,
    ):
        def _fail(*args, **kwargs):
            raise AssertionError("Security must not be created in dry run")

        monkeypatch.setattr("main_with_cli.Security", _fail)

        result = self._run_dry(
            geodiff_real_coord_update_json,
            geodiff_schema_json,
            mock_settings,
            mock_cli_runner,
            mock_cli_app,
            mock_geodiff,
            mock_wkb_loader,
            mock_logger,
        )

        assert result is True

    def test_run_action_dry_run_delete_not_implemented(
        self,
        geodiff_schema_json,
        geodiff_delete_json,
        mock_settings,
        mock_cli_runner,
        mock_cli_app,
        mock_geodiff,
        mock_wkb_loader,
        mock_logger,
        captured_dry_runners,
    ):
        result = self._run_dry(
            geodiff_delete_json,
            geodiff_schema_json,
            mock_settings,
            mock_cli_runner,
            mock_cli_app,
            mock_geodiff,
            mock_wkb_loader,
            mock_logger,
        )

        # delete is not implemented yet, but no CLI call is made anyway
        assert result is False
        assert captured_dry_runners[0].calls == []

    def test_run_action_dry_run_invalid_report_still_fails(
        self,
        geodiff_schema_json,
        mock_settings,
        mock_cli_runner,
        mock_cli_app,
        mock_geodiff,
        mock_wkb_loader,
        mock_logger,
    ):
        result = self._run_dry(
            "invalid json",
            geodiff_schema_json,
            mock_settings,
            mock_cli_runner,
            mock_cli_app,
            mock_geodiff,
            mock_wkb_loader,
            mock_logger,
        )

        assert result is False
        assert mock_cli_runner.invocations == []

    def test_run_action_dry_run_invalid_schema_still_fails(
        self,
        geodiff_real_coord_update_json,
        mock_settings,
        mock_cli_runner,
        mock_cli_app,
        mock_geodiff,
        mock_wkb_loader,
        mock_logger,
    ):
        result = self._run_dry(
            geodiff_real_coord_update_json,
            "not a schema",
            mock_settings,
            mock_cli_runner,
            mock_cli_app,
            mock_geodiff,
            mock_wkb_loader,
            mock_logger,
        )

        assert result is False
        assert mock_cli_runner.invocations == []

    def test_run_action_without_dry_run_authenticates(
        self,
        geodiff_schema_json,
        geodiff_real_coord_update_json,
        mock_settings,
        mock_cli_runner,
        mock_cli_app,
        mock_geodiff,
        mock_wkb_loader,
        mock_logger,
        monkeypatch,
    ):
        monkeypatch.setattr(
            "main_with_cli.AnncsuConsultazione",
            lambda security: MockAnncsuConsultazione(security),
        )

        result = run_action(
            geodiff_report=geodiff_real_coord_update_json,
            geodiff_schema=geodiff_schema_json,
            settings=mock_settings,
            cli_runner=mock_cli_runner,
            cli_app=mock_cli_app,
            geodiff=mock_geodiff,
            wkb_loader=mock_wkb_loader,
            logger=mock_logger,
            token="test-token",
        )

        assert result is True
        _, first_args = mock_cli_runner.invocations[0]
        assert first_args[:2] == ["auth", "login"]
