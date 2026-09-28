"""Unit tests for the main() function in main_with_cli module.

The main() function is the entry point when running as a GitHub Action.
It imports dependencies, loads settings, and calls run_action().

These tests focus on:
- Successful execution path
- Settings loading failures
- run_action() success and failure scenarios
- Proper error handling and exit codes
"""

import sys

import pytest

# Import the main function to test
from main_with_cli import main


# ============================================================================
# Test Cases for main()
# ============================================================================


class TestMain:
    """Unit tests for the main() function."""

    def test_main_success(self, mock_imports, mock_run_action_success, capsys):
        """Test main() executes successfully and exits with code 0."""
        # Should not raise SystemExit, just return normally
        main()

        # Capture printed output
        captured = capsys.readouterr()
        assert "Anncsu Update Action completed successfully" in captured.out

        # Check that core.info was called with startup message
        core = mock_imports["core"]
        info_messages = [msg for level, msg in core.messages if level == "info"]
        assert any("Starting Anncsu Update Action" in msg for msg in info_messages)

    def test_main_run_action_failure(self, mock_imports, mock_run_action_failure):
        """Test main() exits with code 1 when run_action returns False."""
        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 1

    def test_main_settings_loading_failure(self, mock_imports, monkeypatch):
        """Test main() exits with code 1 when settings loading fails."""

        def mock_settings_error():
            raise ValueError("Invalid settings")

        # Patch the settings class to raise an exception
        import sys

        sys.modules["settings"].AnncsuUpdateSettings = mock_settings_error

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 1

        # Check that the original exception is preserved in the chain
        assert exc_info.value.__cause__ is not None
        assert isinstance(exc_info.value.__cause__, ValueError)
        assert str(exc_info.value.__cause__) == "Invalid settings"

    def test_main_gets_required_inputs(self, mock_imports, mock_run_action_success):
        """Test main() retrieves required inputs from core.get_input."""
        core = mock_imports["core"]

        # Track which inputs were requested
        requested_inputs = []

        original_get_input = core.get_input

        def tracking_get_input(name: str, required: bool = False) -> str:
            requested_inputs.append((name, required))
            return original_get_input(name, required)

        core.get_input = tracking_get_input

        main()

        # Verify the required inputs were requested
        assert ("geodiff_report", True) in requested_inputs
        assert ("token", True) in requested_inputs

    def test_main_loads_settings(self, mock_imports, mock_run_action_success, monkeypatch):
        """Test main() loads AnncsuUpdateSettings."""
        settings_loaded = []

        original_settings_class = sys.modules["settings"].AnncsuUpdateSettings

        def tracking_settings_init():
            settings_loaded.append(True)
            return original_settings_class()

        monkeypatch.setattr(sys.modules["settings"], "AnncsuUpdateSettings", tracking_settings_init)

        main()

        assert len(settings_loaded) == 1

    def test_main_creates_cli_runner(self, mock_imports, mock_run_action_success, monkeypatch):
        """Test main() creates a CliRunner instance."""
        cli_runner_created = []

        original_cli_runner = sys.modules["typer.testing"].CliRunner

        class TrackingCliRunner(original_cli_runner):
            def __init__(self):
                cli_runner_created.append(True)
                super().__init__()

        monkeypatch.setattr(sys.modules["typer.testing"], "CliRunner", TrackingCliRunner)

        main()

        assert len(cli_runner_created) == 1

    def test_main_calls_run_action_with_correct_parameters(self, mock_imports, monkeypatch):
        """Test main() calls run_action with the correct parameters."""
        run_action_calls = []

        def tracking_run_action(**kwargs):
            run_action_calls.append(kwargs)
            return True

        monkeypatch.setattr("main_with_cli.run_action", tracking_run_action)

        main()

        assert len(run_action_calls) == 1
        call_kwargs = run_action_calls[0]

        # Verify all required parameters are passed
        assert "geodiff_report" in call_kwargs
        assert "settings" in call_kwargs
        assert "cli_runner" in call_kwargs
        assert "cli_app" in call_kwargs
        assert "geodiff" in call_kwargs
        assert "wkb_loader" in call_kwargs
        assert "logger" in call_kwargs
        assert "token" in call_kwargs
        assert "api_type" in call_kwargs

        # Verify specific values
        assert call_kwargs["geodiff_report"] == "/fake/geodiff_report.json"
        assert call_kwargs["token"] == "fake-token"
        assert call_kwargs["api_type"] == "pa"

    @pytest.mark.parametrize("dry_run", [False, True])
    def test_main_passes_dry_run_from_settings(self, mock_imports, monkeypatch, dry_run):
        """Test main() forwards settings.dry_run to run_action."""
        run_action_calls = []

        def tracking_run_action(**kwargs):
            run_action_calls.append(kwargs)
            return True

        original_settings_class = sys.modules["settings"].AnncsuUpdateSettings

        def settings_with_dry_run():
            settings = original_settings_class()
            settings.dry_run = dry_run
            return settings

        monkeypatch.setattr(sys.modules["settings"], "AnncsuUpdateSettings", settings_with_dry_run)
        monkeypatch.setattr("main_with_cli.run_action", tracking_run_action)

        main()

        assert run_action_calls[0]["dry_run"] is dry_run

    def test_main_logs_startup_version(self, mock_imports, mock_run_action_success):
        """Test main() logs the startup message with version."""
        core = mock_imports["core"]
        core.version = "2.3.4-test"

        main()

        info_messages = [msg for level, msg in core.messages if level == "info"]
        assert any("Starting Anncsu Update Action" in msg and "2.3.4-test" in msg for msg in info_messages)

    def test_main_logs_geodiff_report_input(self, mock_imports, mock_run_action_success):
        """Test main() logs the geodiff_report input."""
        main()

        core = mock_imports["core"]
        info_messages = [msg for level, msg in core.messages if level == "info"]
        assert any("geodiff_report:" in msg and "/fake/geodiff_report.json" in msg for msg in info_messages)

    def test_main_calls_check_output_for_uv(self, mock_imports, mock_run_action_success, monkeypatch):
        """Test main() calls functions.check_output to verify uv."""
        check_output_calls = []

        def tracking_check_output(cmd: str, raise_on_error: bool) -> str:
            check_output_calls.append((cmd, raise_on_error))
            return "Mock output"

        monkeypatch.setattr(sys.modules["functions"], "check_output", tracking_check_output)

        main()

        # Verify uv commands were called
        assert any("uv -V" in cmd for cmd, _ in check_output_calls)
        assert any("uv python dir" in cmd for cmd, _ in check_output_calls)

    def test_main_creates_geodiff_instance(self, mock_imports, mock_run_action_success, monkeypatch):
        """Test main() creates a GeoDiff instance."""
        geodiff_created = []

        original_geodiff = sys.modules["pygeodiff"].GeoDiff

        class TrackingGeoDiff(original_geodiff):
            def __init__(self):
                geodiff_created.append(True)
                super().__init__()

        monkeypatch.setattr(sys.modules["pygeodiff"], "GeoDiff", TrackingGeoDiff)

        main()

        assert len(geodiff_created) == 1

    def test_main_uses_shapely_wkb_loads(self, mock_imports, mock_run_action_success, monkeypatch):
        """Test main() passes shapely.wkb.loads to run_action."""
        run_action_calls = []

        def tracking_run_action(**kwargs):
            run_action_calls.append(kwargs)
            return True

        monkeypatch.setattr("main_with_cli.run_action", tracking_run_action)

        main()

        call_kwargs = run_action_calls[0]
        # Verify wkb_loader is the mocked function (check function name)
        assert call_kwargs["wkb_loader"].__name__ == "mock_wkb_loads_for_main"
        assert callable(call_kwargs["wkb_loader"])

    def test_main_passes_core_as_logger(self, mock_imports, mock_run_action_success, monkeypatch):
        """Test main() passes actions.core as the logger parameter."""
        run_action_calls = []

        def tracking_run_action(**kwargs):
            run_action_calls.append(kwargs)
            return True

        monkeypatch.setattr("main_with_cli.run_action", tracking_run_action)

        main()

        call_kwargs = run_action_calls[0]
        assert call_kwargs["logger"] == mock_imports["core"]

    def test_main_logs_github_context(self, mock_imports, mock_run_action_success):
        """Test main() logs GitHub context data in debug mode."""
        main()

        core = mock_imports["core"]
        debug_messages = [msg for level, msg in core.messages if level == "debug"]

        # Should have debug messages with context data
        assert len(debug_messages) > 0

    def test_main_groups_output_for_uv_and_context(self, mock_imports, mock_run_action_success):
        """Test main() uses core.group for organizing output."""
        group_calls = []
        original_group = mock_imports["core"].group

        def tracking_group(name: str):
            group_calls.append(name)
            return original_group(name)

        mock_imports["core"].group = tracking_group

        main()

        # Verify groups were created
        assert "uv" in group_calls
        assert "GitHub Context Data" in group_calls


# ============================================================================
# Edge Cases and Error Scenarios
# ============================================================================


class TestMainEdgeCases:
    """Test edge cases and error scenarios for main()."""

    def test_main_with_empty_geodiff_report_input(self, mock_imports, mock_run_action_success, monkeypatch):
        """Test main() when geodiff_report input is empty."""

        def mock_get_input_empty(name: str, required: bool = False) -> str:
            if name == "geodiff_report":
                return ""
            if name == "token":
                return "fake-token"
            return ""

        mock_imports["core"].get_input = mock_get_input_empty

        # Should still run (run_action will handle the empty input)
        main()

    def test_main_settings_validation_error(self, mock_imports, monkeypatch):
        """Test main() when settings validation fails."""

        def mock_settings_validation_error():
            raise ValueError("codice_comune is required")

        monkeypatch.setattr(sys.modules["settings"], "AnncsuUpdateSettings", mock_settings_validation_error)

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 1

        # Check that the original exception is preserved in the chain        assert exc_info.value.__cause__ is not None
        assert isinstance(exc_info.value.__cause__, ValueError)
        assert str(exc_info.value.__cause__) == "codice_comune is required"

    def test_main_preserves_exception_chain(self, mock_imports, monkeypatch):
        """Test main() preserves the exception chain when re-raising."""

        def mock_settings_error():
            raise RuntimeError("Original error")

        monkeypatch.setattr(sys.modules["settings"], "AnncsuUpdateSettings", mock_settings_error)

        with pytest.raises(SystemExit) as exc_info:
            main()

        # SystemExit should be raised
        assert exc_info.value.code == 1

        # Check that the original exception is preserved in the chain
        assert exc_info.value.__cause__ is not None
        assert isinstance(exc_info.value.__cause__, RuntimeError)
        assert str(exc_info.value.__cause__) == "Original error"

    def test_main_with_different_api_type(self, mock_imports, monkeypatch):
        """Test main() uses 'pa' as the api_type parameter."""
        run_action_calls = []

        def tracking_run_action(**kwargs):
            run_action_calls.append(kwargs)
            return True

        monkeypatch.setattr("main_with_cli.run_action", tracking_run_action)

        main()

        call_kwargs = run_action_calls[0]
        assert call_kwargs["api_type"] == "pa"
