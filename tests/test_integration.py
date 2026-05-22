"""Integration tests for main_with_cli module.

These tests mirror the integration tests defined in .github/workflows/test.yaml
and test the full flow of processing geodiff reports.

Mark tests that require external resources with @pytest.mark.integration
"""

import json

from geodiff_models import GeodiffFile
from main_with_cli import (
    load_geodiff_report,
    process_all_entries,
    run_action,
)
from conftest import MockCliResult, MockGeometry, MockAnncsuConsultazione


# ============================================================================
# Integration Tests - Load geodiff report from file
# ============================================================================


class TestLoadGeodiffReportIntegration:
    """Integration tests for loading geodiff reports from files."""

    def test_load_update_report_from_file(self, geodiff_update_report_file, mock_logger):
        """Test loading an update report from file (mirrors test-anncsu-update workflow)."""
        result = load_geodiff_report(str(geodiff_update_report_file), mock_logger)

        assert result is not None
        assert len(result.geodiff) == 1
        assert result.geodiff[0].type == "update"
        assert result.geodiff[0].table == "WhereAbouts_fails"

    def test_load_delete_report_from_file(self, geodiff_delete_report_file, mock_logger):
        """Test loading a delete report from file (mirrors test-delete-check-with-geodiff)."""
        result = load_geodiff_report(str(geodiff_delete_report_file), mock_logger)

        assert result is not None
        assert len(result.geodiff) == 2
        assert all(entry.type == "delete" for entry in result.geodiff)

    def test_load_insert_report_from_file(self, geodiff_insert_report_file, mock_logger):
        """Test loading an insert report from file (mirrors test-insert-check-with-geodiff)."""
        result = load_geodiff_report(str(geodiff_insert_report_file), mock_logger)

        assert result is not None
        assert len(result.geodiff) == 2
        assert all(entry.type == "insert" for entry in result.geodiff)

    def test_load_mixed_report_from_file(self, geodiff_mixed_report_file, mock_logger):
        """Test loading a mixed operations report from file."""
        result = load_geodiff_report(str(geodiff_mixed_report_file), mock_logger)

        assert result is not None
        assert len(result.geodiff) == 3
        types = [entry.type for entry in result.geodiff]
        assert "update" in types
        assert "insert" in types
        assert "delete" in types


# ============================================================================
# Integration Tests - Process entries from file
# ============================================================================


class TestProcessEntriesIntegration:
    """Integration tests for processing geodiff entries from files."""

    def test_process_update_entries_from_file(
        self,
        geodiff_update_report_file,
        mock_settings,
        mock_cli_runner,
        mock_cli_app,
        mock_geodiff,
        mock_logger,
        mock_anncsu_consultazione,
    ):
        """Test processing update entries loaded from a file.

        Note: This test uses an update without geometry, so it will fail
        (return False) because no geometry is present.
        """
        geodiff_file = GeodiffFile.from_path(geodiff_update_report_file)

        def mock_wkb_loader(data):
            return MockGeometry()

        results = process_all_entries(
            geodiff_file=geodiff_file,
            settings=mock_settings,
            cli_runner=mock_cli_runner,
            cli_app=mock_cli_app,
            geodiff=mock_geodiff,
            wkb_loader=mock_wkb_loader,
            logger=mock_logger,
            anncsu_sdk=mock_anncsu_consultazione,
        )

        assert len(results) == 1
        assert results[0].entry_type == "update"
        # Entry has no geometry, so processing fails
        assert results[0].success is False

    def test_process_delete_entries_from_file(
        self,
        geodiff_delete_report_file,
        mock_settings,
        mock_cli_runner,
        mock_cli_app,
        mock_geodiff,
        mock_logger,
        mock_anncsu_consultazione,
    ):
        """Test processing delete entries loaded from a file."""
        geodiff_file = GeodiffFile.from_path(geodiff_delete_report_file)

        def mock_wkb_loader(data):
            return MockGeometry()

        results = process_all_entries(
            geodiff_file=geodiff_file,
            settings=mock_settings,
            cli_runner=mock_cli_runner,
            cli_app=mock_cli_app,
            geodiff=mock_geodiff,
            wkb_loader=mock_wkb_loader,
            logger=mock_logger,
            anncsu_sdk=mock_anncsu_consultazione,
        )

        assert len(results) == 2
        assert all(r.entry_type == "delete" for r in results)
        # Delete entries with geometry should succeed (delete is TODO, returns True)
        assert all(r.success for r in results)

    def test_process_insert_entries_from_file(
        self,
        geodiff_insert_report_file,
        mock_settings,
        mock_cli_runner,
        mock_cli_app,
        mock_geodiff,
        mock_logger,
        mock_anncsu_consultazione,
    ):
        """Test processing insert entries loaded from a file."""

        geodiff_file = GeodiffFile.from_path(geodiff_insert_report_file)

        def mock_wkb_loader(data):
            return MockGeometry()

        results = process_all_entries(
            geodiff_file=geodiff_file,
            settings=mock_settings,
            cli_runner=mock_cli_runner,
            cli_app=mock_cli_app,
            geodiff=mock_geodiff,
            wkb_loader=mock_wkb_loader,
            logger=mock_logger,
            anncsu_sdk=mock_anncsu_consultazione,
        )

        assert len(results) == 2
        assert all(r.entry_type == "insert" for r in results)
        # Insert entries with geometry should succeed (insert is TODO, returns True)
        assert all(r.success for r in results)

    def test_process_mixed_entries_from_file(
        self,
        geodiff_mixed_report_file,
        mock_settings,
        mock_cli_runner,
        mock_cli_app,
        mock_geodiff,
        mock_logger,
        mock_anncsu_consultazione,
    ):
        """Test processing mixed operation entries from a file."""

        geodiff_file = GeodiffFile.from_path(geodiff_mixed_report_file)

        def mock_wkb_loader(data):
            return MockGeometry()

        results = process_all_entries(
            geodiff_file=geodiff_file,
            settings=mock_settings,
            cli_runner=mock_cli_runner,
            cli_app=mock_cli_app,
            geodiff=mock_geodiff,
            wkb_loader=mock_wkb_loader,
            logger=mock_logger,
            anncsu_sdk=mock_anncsu_consultazione,
        )

        assert len(results) == 3
        entry_types = [r.entry_type for r in results]
        assert "update" in entry_types
        assert "insert" in entry_types
        assert "delete" in entry_types


# ============================================================================
# Integration Tests - Full run_action flow
# ============================================================================


class TestRunActionIntegration:
    """Integration tests for the full run_action flow with file-based reports."""

    def test_run_action_with_delete_report_file(
        self,
        geodiff_delete_report_file,
        mock_settings,
        mock_cli_runner,
        mock_cli_app,
        mock_geodiff,
        mock_logger,
    ):
        """Test full run_action flow with a delete report file."""

        def mock_wkb_loader(data):
            return MockGeometry()

        result = run_action(
            geodiff_report=str(geodiff_delete_report_file),
            settings=mock_settings,
            cli_runner=mock_cli_runner,
            cli_app=mock_cli_app,
            geodiff=mock_geodiff,
            wkb_loader=mock_wkb_loader,
            logger=mock_logger,
            token="test-token",
        )

        assert result is True
        # Auth call + no CLI calls for delete (TODO)
        assert len(mock_cli_runner.invocations) >= 1

    def test_run_action_with_insert_report_file(
        self,
        geodiff_insert_report_file,
        mock_settings,
        mock_cli_runner,
        mock_cli_app,
        mock_geodiff,
        mock_logger,
        monkeypatch,
    ):
        """Test full run_action flow with an insert report file."""
        # Mock the AnncsuConsultazione SDK to avoid real API calls
        monkeypatch.setattr(
            "main_with_cli.AnncsuConsultazione",
            lambda security: MockAnncsuConsultazione(),
        )

        def mock_wkb_loader(data):
            return MockGeometry()

        result = run_action(
            geodiff_report=str(geodiff_insert_report_file),
            settings=mock_settings,
            cli_runner=mock_cli_runner,
            cli_app=mock_cli_app,
            geodiff=mock_geodiff,
            wkb_loader=mock_wkb_loader,
            logger=mock_logger,
            token="test-token",
        )

        assert result is True
        # Auth call + no CLI calls for insert (TODO)
        assert len(mock_cli_runner.invocations) >= 1

    def test_run_action_with_mixed_report_file(
        self,
        geodiff_mixed_report_file,
        mock_settings,
        mock_cli_runner,
        mock_cli_app,
        mock_geodiff,
        mock_logger,
        monkeypatch,
    ):
        """Test full run_action flow with a mixed operations report file."""
        # Mock the AnncsuConsultazione SDK to avoid real API calls
        monkeypatch.setattr(
            "main_with_cli.AnncsuConsultazione",
            lambda security: MockAnncsuConsultazione(),
        )

        def mock_wkb_loader(data):
            return MockGeometry()

        result = run_action(
            geodiff_report=str(geodiff_mixed_report_file),
            settings=mock_settings,
            cli_runner=mock_cli_runner,
            cli_app=mock_cli_app,
            geodiff=mock_geodiff,
            wkb_loader=mock_wkb_loader,
            logger=mock_logger,
            token="test-token",
        )

        assert result is True
        # Auth call + update CLI call
        assert len(mock_cli_runner.invocations) >= 2

    def test_run_action_auth_then_process(
        self,
        geodiff_mixed_report_file,
        mock_settings,
        mock_cli_app,
        mock_geodiff,
        mock_logger,
        monkeypatch,
    ):
        """Test that run_action authenticates before processing entries."""
        # Mock the AnncsuConsultazione SDK to avoid real API calls
        monkeypatch.setattr(
            "main_with_cli.AnncsuConsultazione",
            lambda security: MockAnncsuConsultazione(),
        )

        call_order = []

        class TrackingCliRunner:
            def __init__(self):
                self.invocations = []

            def invoke(self, app, args):
                self.invocations.append(args)
                if "auth" in args:
                    call_order.append("auth")
                    return MockCliResult(exit_code=0, output="OK")
                elif "accesso" in args:
                    return MockCliResult(exit_code=0, output='[{"coordX": 10.0, "coordY": 50.0}]')
                elif "coordinate" in args:
                    call_order.append("coordinate")
                return MockCliResult(exit_code=0, output="OK")

        cli_runner = TrackingCliRunner()

        def mock_wkb_loader(data):
            return MockGeometry()

        result = run_action(
            geodiff_report=str(geodiff_mixed_report_file),
            settings=mock_settings,
            cli_runner=cli_runner,
            cli_app=mock_cli_app,
            geodiff=mock_geodiff,
            wkb_loader=mock_wkb_loader,
            logger=mock_logger,
            token="test-token",
        )

        assert result is True
        # Auth should be called first
        assert call_order[0] == "auth"
        # Then coordinate update for the update entry
        assert "coordinate" in call_order


# ============================================================================
# Integration Tests - Error scenarios
# ============================================================================


class TestErrorScenariosIntegration:
    """Integration tests for error handling scenarios."""

    def test_run_action_with_malformed_json_file(
        self, tmp_path, mock_settings, mock_cli_runner, mock_cli_app, mock_geodiff, mock_logger
    ):
        """Test run_action with a file containing malformed JSON."""
        malformed_file = tmp_path / "malformed.json"
        malformed_file.write_text("{ this is not valid json }")

        def mock_wkb_loader(data):
            return MockGeometry()

        result = run_action(
            geodiff_report=str(malformed_file),
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

    def test_run_action_with_valid_json_invalid_schema(
        self, tmp_path, mock_settings, mock_cli_runner, mock_cli_app, mock_geodiff, mock_logger
    ):
        """Test run_action with valid JSON but invalid geodiff schema."""
        invalid_schema_file = tmp_path / "invalid_schema.json"
        invalid_schema_file.write_text('{"foo": "bar"}')

        def mock_wkb_loader(data):
            return MockGeometry()

        result = run_action(
            geodiff_report=str(invalid_schema_file),
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

    def test_run_action_with_empty_geodiff_file(
        self, tmp_path, mock_settings, mock_cli_runner, mock_cli_app, mock_geodiff, mock_logger
    ):
        """Test run_action with an empty geodiff entries array."""
        empty_file = tmp_path / "empty.json"
        empty_file.write_text('{"geodiff": []}')

        def mock_wkb_loader(data):
            return MockGeometry()

        result = run_action(
            geodiff_report=str(empty_file),
            settings=mock_settings,
            cli_runner=mock_cli_runner,
            cli_app=mock_cli_app,
            geodiff=mock_geodiff,
            wkb_loader=mock_wkb_loader,
            logger=mock_logger,
            token="test-token",
        )

        # Empty is success (nothing to process)
        assert result is True


# ============================================================================
# Integration Tests - Geodiff comparison (mirrors test.yaml workflow)
# ============================================================================


class TestGeodiffComparison:
    """Integration tests that use geodiff to compare GeoPackage files.

    These tests mirror the integration tests in .github/workflows/test.yaml:
    - test-delete-check-with-geodiff
    - test-update-check-with-geodiff
    - test-insert-check-with-geodiff
    """

    def test_geodiff_detects_delete_operations(self, base_geopackage, tmp_path):
        """Test that geodiff correctly detects delete operations.

        Mirrors: test-delete-check-with-geodiff in test.yaml
        Expected: 2 deletions (fid 2 and 4)
        """
        import shutil
        import sqlite3
        from pygeodiff import GeoDiff

        # Create a copy for the modified version
        modified_gpkg = tmp_path / "modified.gpkg"
        shutil.copy(base_geopackage, modified_gpkg)

        # Delete records with fid 2 and 4
        conn = sqlite3.connect(modified_gpkg)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM test_layer WHERE fid = 2 OR fid = 4")
        conn.commit()
        conn.close()

        # Use geodiff to compare
        geodiff = GeoDiff()
        changeset_path = str(tmp_path / "changeset.bin")
        summary_json_path = str(tmp_path / "summary.json")

        # Create changeset (base -> modified)
        geodiff.create_changeset(str(base_geopackage), str(modified_gpkg), changeset_path)

        # Get summary (writes to JSON file)
        geodiff.list_changes_summary(changeset_path, summary_json_path)

        # Read and parse the summary
        with open(summary_json_path) as f:
            result = json.load(f)
        summary = result.get("geodiff_summary", [])

        # Verify the expected deletions are detected
        assert len(summary) == 1
        table_summary = summary[0]
        assert table_summary["table"] == "test_layer"
        assert table_summary["delete"] == 2
        assert table_summary["insert"] == 0
        assert table_summary["update"] == 0

    def test_geodiff_detects_update_operations(self, base_geopackage, tmp_path):
        """Test that geodiff correctly detects update operations.

        Mirrors: test-update-check-with-geodiff in test.yaml
        Expected: 2 updates (fid 2 and 4 name changed)
        """
        import shutil
        import sqlite3
        from pygeodiff import GeoDiff

        # Create a copy for the modified version
        modified_gpkg = tmp_path / "modified.gpkg"
        shutil.copy(base_geopackage, modified_gpkg)

        # Update records with fid 2 and 4
        conn = sqlite3.connect(modified_gpkg)
        cursor = conn.cursor()
        cursor.execute("UPDATE test_layer SET name = 'Updated Point B' WHERE fid = 2")
        cursor.execute("UPDATE test_layer SET name = 'Updated Point D' WHERE fid = 4")
        conn.commit()
        conn.close()

        # Use geodiff to compare
        geodiff = GeoDiff()
        changeset_path = str(tmp_path / "changeset.bin")
        summary_json_path = str(tmp_path / "summary.json")

        # Create changeset (base -> modified)
        geodiff.create_changeset(str(base_geopackage), str(modified_gpkg), changeset_path)

        # Get summary (writes to JSON file)
        geodiff.list_changes_summary(changeset_path, summary_json_path)

        # Read and parse the summary
        with open(summary_json_path) as f:
            result = json.load(f)
        summary = result.get("geodiff_summary", [])

        # Verify the expected updates are detected
        assert len(summary) == 1
        table_summary = summary[0]
        assert table_summary["table"] == "test_layer"
        assert table_summary["delete"] == 0
        assert table_summary["insert"] == 0
        assert table_summary["update"] == 2

    def test_geodiff_detects_insert_operations(self, base_geopackage, tmp_path):
        """Test that geodiff correctly detects insert operations.

        Mirrors: test-insert-check-with-geodiff in test.yaml
        Expected: 2 insertions (fid 6 and 7)
        """
        import shutil
        import sqlite3
        from pygeodiff import GeoDiff

        # Create a copy for the modified version
        modified_gpkg = tmp_path / "modified.gpkg"
        shutil.copy(base_geopackage, modified_gpkg)

        # Insert new records
        conn = sqlite3.connect(modified_gpkg)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO test_layer (fid, name, address_id, road_id) VALUES (6, 'Inserted Point F', 6, 606)"
        )
        cursor.execute(
            "INSERT INTO test_layer (fid, name, address_id, road_id) VALUES (7, 'Inserted Point G', 7, 707)"
        )
        conn.commit()
        conn.close()

        # Use geodiff to compare
        geodiff = GeoDiff()
        changeset_path = str(tmp_path / "changeset.bin")
        summary_json_path = str(tmp_path / "summary.json")

        # Create changeset (base -> modified)
        geodiff.create_changeset(str(base_geopackage), str(modified_gpkg), changeset_path)

        # Get summary (writes to JSON file)
        geodiff.list_changes_summary(changeset_path, summary_json_path)

        # Read and parse the summary
        with open(summary_json_path) as f:
            result = json.load(f)
        summary = result.get("geodiff_summary", [])

        # Verify the expected insertions are detected
        assert len(summary) == 1
        table_summary = summary[0]
        assert table_summary["table"] == "test_layer"
        assert table_summary["delete"] == 0
        assert table_summary["insert"] == 2
        assert table_summary["update"] == 0

    def test_geodiff_detects_mixed_operations(self, base_geopackage, tmp_path):
        """Test that geodiff correctly detects mixed operations.

        Expected: 1 deletion, 1 update, 1 insertion
        """
        import shutil
        import sqlite3
        from pygeodiff import GeoDiff

        # Create a copy for the modified version
        modified_gpkg = tmp_path / "modified.gpkg"
        shutil.copy(base_geopackage, modified_gpkg)

        # Apply mixed changes
        conn = sqlite3.connect(modified_gpkg)
        cursor = conn.cursor()
        # Delete fid 5
        cursor.execute("DELETE FROM test_layer WHERE fid = 5")
        # Update fid 1
        cursor.execute("UPDATE test_layer SET name = 'Updated Point A' WHERE fid = 1")
        # Insert fid 6
        cursor.execute("INSERT INTO test_layer (fid, name, address_id, road_id) VALUES (6, 'New Point F', 6, 606)")
        conn.commit()
        conn.close()

        # Use geodiff to compare
        geodiff = GeoDiff()
        changeset_path = str(tmp_path / "changeset.bin")
        summary_json_path = str(tmp_path / "summary.json")

        # Create changeset (base -> modified)
        geodiff.create_changeset(str(base_geopackage), str(modified_gpkg), changeset_path)

        # Get summary (writes to JSON file)
        geodiff.list_changes_summary(changeset_path, summary_json_path)

        # Read and parse the summary
        with open(summary_json_path) as f:
            result = json.load(f)
        summary = result.get("geodiff_summary", [])

        # Verify the expected changes are detected
        assert len(summary) == 1
        table_summary = summary[0]
        assert table_summary["table"] == "test_layer"
        assert table_summary["delete"] == 1
        assert table_summary["insert"] == 1
        assert table_summary["update"] == 1

    def test_geodiff_detailed_changes(self, base_geopackage, tmp_path):
        """Test retrieving detailed changes from geodiff.

        This tests the detailed change detection that the action uses
        to extract specific column changes.
        """
        import shutil
        import sqlite3
        from pygeodiff import GeoDiff

        # Create a copy for the modified version
        modified_gpkg = tmp_path / "modified.gpkg"
        shutil.copy(base_geopackage, modified_gpkg)

        # Update a specific record
        conn = sqlite3.connect(modified_gpkg)
        cursor = conn.cursor()
        cursor.execute("UPDATE test_layer SET name = 'Changed Name', road_id = 999 WHERE fid = 1")
        conn.commit()
        conn.close()

        # Use geodiff to compare
        geodiff = GeoDiff()
        changeset_path = str(tmp_path / "changeset.bin")
        changes_json_path = str(tmp_path / "changes.json")

        # Create changeset (base -> modified)
        geodiff.create_changeset(str(base_geopackage), str(modified_gpkg), changeset_path)

        # Get detailed changes (writes to JSON file)
        geodiff.list_changes(changeset_path, changes_json_path)

        # Read and parse the changes
        with open(changes_json_path) as f:
            result = json.load(f)
        changes = result.get("geodiff", [])

        # Verify we got detailed change info
        assert len(changes) == 1
        table_changes = changes[0]
        assert table_changes["table"] == "test_layer"
        assert table_changes["type"] == "update"
        assert "changes" in table_changes

        # Verify the column changes are captured
        column_changes = table_changes["changes"]
        assert len(column_changes) > 0

    def test_geodiff_no_changes(self, base_geopackage, tmp_path):
        """Test that geodiff correctly reports no changes when files are identical."""
        import shutil
        from pygeodiff import GeoDiff

        # Create an identical copy
        modified_gpkg = tmp_path / "modified.gpkg"
        shutil.copy(base_geopackage, modified_gpkg)

        # Use geodiff to compare
        geodiff = GeoDiff()
        changeset_path = str(tmp_path / "changeset.bin")
        summary_json_path = str(tmp_path / "summary.json")

        # Create changeset (base -> modified)
        geodiff.create_changeset(str(base_geopackage), str(modified_gpkg), changeset_path)

        # Get summary (writes to JSON file)
        geodiff.list_changes_summary(changeset_path, summary_json_path)

        # Read and parse the summary
        with open(summary_json_path) as f:
            result = json.load(f)
        summary = result.get("geodiff_summary", [])

        # No changes should be detected
        assert len(summary) == 0

    def test_geodiff_detects_plugin_score_and_geocoder_changes(self, base_geopackage, tmp_path):
        """Test that geodiff detects changes to plugin_score and plugin_geocoder columns.

        base_geopackage rows 3-5 have pre-set plugin_score / plugin_geocoder values.
        This test modifies them and verifies geodiff picks up the change.
        """
        import shutil
        import sqlite3
        from pygeodiff import GeoDiff

        modified_gpkg = tmp_path / "modified.gpkg"
        shutil.copy(base_geopackage, modified_gpkg)

        conn = sqlite3.connect(modified_gpkg)
        cursor = conn.cursor()
        # Change plugin_score from 0.5 → 1.0 and plugin_geocoder from OTHER → ANNCSU
        cursor.execute("UPDATE test_layer SET plugin_score = 1.0, plugin_geocoder = 'ANNCSU' WHERE fid = 3")
        # Change plugin_score from 1.0 → 0.8 on fid=4 (was already ANNCSU geocoder)
        cursor.execute("UPDATE test_layer SET plugin_score = 0.8 WHERE fid = 4")
        conn.commit()
        conn.close()

        geodiff = GeoDiff()
        changeset_path = str(tmp_path / "changeset.bin")
        summary_json_path = str(tmp_path / "summary.json")

        geodiff.create_changeset(str(base_geopackage), str(modified_gpkg), changeset_path)
        geodiff.list_changes_summary(changeset_path, summary_json_path)

        with open(summary_json_path) as f:
            result = json.load(f)
        summary = result.get("geodiff_summary", [])

        assert len(summary) == 1
        table_summary = summary[0]
        assert table_summary["table"] == "test_layer"
        assert table_summary["update"] == 2
        assert table_summary["delete"] == 0
        assert table_summary["insert"] == 0


# ============================================================================
# Integration Tests - PLUGIN_SCORE / PLUGIN_GEOCODER skip logic
# ============================================================================


class TestPluginSkipIntegration:
    """Integration tests for the PLUGIN_SCORE=1.0 / PLUGIN_GEOCODER=ANNCSU skip logic."""

    def test_process_entries_all_skipped_when_plugin_score_1_and_geocoder_anncsu(
        self,
        geodiff_plugin_skip_report_file,
        mock_settings,
        mock_cli_runner,
        mock_cli_app,
        mock_geodiff,
        mock_logger,
        mock_anncsu_consultazione,
    ):
        """All entries with PLUGIN_SCORE=1.0 and PLUGIN_GEOCODER=ANNCSU must be skipped.

        No CLI calls should be made; each entry returns True (success).
        """
        geodiff_file = GeodiffFile.from_path(geodiff_plugin_skip_report_file)

        def mock_wkb_loader(data):
            from conftest import MockGeometry

            return MockGeometry()

        results = process_all_entries(
            geodiff_file=geodiff_file,
            settings=mock_settings,
            cli_runner=mock_cli_runner,
            cli_app=mock_cli_app,
            geodiff=mock_geodiff,
            wkb_loader=mock_wkb_loader,
            logger=mock_logger,
            anncsu_sdk=mock_anncsu_consultazione,
        )

        assert len(results) == 2
        assert all(r.success for r in results)
        # No CLI invocations — skip logic fired before any CLI call
        assert len(mock_cli_runner.invocations) == 0
        info_messages = [msg for level, msg in mock_logger.messages if level == "info"]
        assert sum(1 for m in info_messages if "PLUGIN_SCORE=1.0" in m and "PLUGIN_GEOCODER=ANNCSU" in m) == 2

    def test_process_entries_not_skipped_when_plugin_conditions_not_met(
        self,
        geodiff_plugin_no_skip_report_file,
        mock_settings,
        mock_cli_runner,
        mock_cli_app,
        mock_geodiff,
        mock_logger,
        mock_anncsu_consultazione,
    ):
        """Entries that do NOT meet the skip condition must be processed via CLI."""
        geodiff_file = GeodiffFile.from_path(geodiff_plugin_no_skip_report_file)

        def mock_wkb_loader(data):
            return MockGeometry()

        results = process_all_entries(
            geodiff_file=geodiff_file,
            settings=mock_settings,
            cli_runner=mock_cli_runner,
            cli_app=mock_cli_app,
            geodiff=mock_geodiff,
            wkb_loader=mock_wkb_loader,
            logger=mock_logger,
            anncsu_sdk=mock_anncsu_consultazione,
        )

        assert len(results) == 2
        assert all(r.success for r in results)
        # Both entries must have triggered CLI calls (at least one query each)
        assert len(mock_cli_runner.invocations) >= 2

    def test_run_action_skips_plugin_score_anncsu_entries(
        self,
        geodiff_plugin_skip_report_file,
        mock_settings,
        mock_cli_runner,
        mock_cli_app,
        mock_geodiff,
        mock_logger,
        monkeypatch,
    ):
        """run_action end-to-end: skipped entries must not cause CLI calls beyond auth."""
        monkeypatch.setattr(
            "main_with_cli.AnncsuConsultazione",
            lambda security: MockAnncsuConsultazione(),
        )

        def mock_wkb_loader(data):
            return MockGeometry()

        result = run_action(
            geodiff_report=str(geodiff_plugin_skip_report_file),
            settings=mock_settings,
            cli_runner=mock_cli_runner,
            cli_app=mock_cli_app,
            geodiff=mock_geodiff,
            wkb_loader=mock_wkb_loader,
            logger=mock_logger,
            token="test-token",
        )

        assert result is True
        # Only the auth call should be present — no query/update calls
        assert len(mock_cli_runner.invocations) == 1
        _, auth_args = mock_cli_runner.invocations[0]
        assert "auth" in auth_args

    def test_run_action_processes_plugin_no_skip_entries(
        self,
        geodiff_plugin_no_skip_report_file,
        mock_settings,
        mock_cli_runner,
        mock_cli_app,
        mock_geodiff,
        mock_logger,
        monkeypatch,
    ):
        """run_action end-to-end: entries that don't meet skip condition are processed."""
        monkeypatch.setattr(
            "main_with_cli.AnncsuConsultazione",
            lambda security: MockAnncsuConsultazione(),
        )

        def mock_wkb_loader(data):
            return MockGeometry()

        result = run_action(
            geodiff_report=str(geodiff_plugin_no_skip_report_file),
            settings=mock_settings,
            cli_runner=mock_cli_runner,
            cli_app=mock_cli_app,
            geodiff=mock_geodiff,
            wkb_loader=mock_wkb_loader,
            logger=mock_logger,
            token="test-token",
        )

        assert result is True
        # auth + at least one query per entry
        assert len(mock_cli_runner.invocations) >= 3
