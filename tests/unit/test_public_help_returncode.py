"""A main invocation without checking its result is not a help-success control."""
from ravel import cli

def test_actual_public_help_reports_success(capsys):
    try:
        result = cli.main(["--help"])
    except SystemExit as exc:
        result = exc.code
    assert result == 0
    output = capsys.readouterr()
    assert "usage: ravel" in output.out
    assert output.err == ""
