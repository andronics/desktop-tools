import re
from collections.abc import Callable
from pathlib import Path

import pytest
from typer.testing import CliRunner

from desktop_tools import __version__
from desktop_tools.cli import app

runner = CliRunner()


def plain(text: str) -> str:
    """text without ANSI codes. In CI (GITHUB_ACTIONS, FORCE_COLOR) rich colours Click's errors,
    and the codes split the words: match error text on plain(result.output)."""
    return re.sub(r"\x1b\[(?:[0-9;]*)m", "", text)


def test_version() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == __version__


def test_config_shows_sources(write_config: Callable[..., Path]) -> None:
    result = runner.invoke(app, ["config", "-c", str(write_config("log_level: debug\n"))])
    assert result.exit_code == 0
    assert "log_level = DEBUG  (file)" in result.stdout


def test_config_error_exits_2(write_config: Callable[..., Path]) -> None:
    result = runner.invoke(app, ["config", "-c", str(write_config("log_level: loud\n"))])
    assert result.exit_code == 2
    assert "log_level" in plain(result.stderr)


def test_unknown_option_exits_2() -> None:
    result = runner.invoke(app, ["config", "--nope"])
    assert result.exit_code == 2
    assert "No such option: --nope" in plain(result.output)


@pytest.fixture
def secret_env(monkeypatch: pytest.MonkeyPatch) -> str:
    """The settings plus a secret `test_only.secret`; returns its variable's name."""
    from interpose.settings import Setting, Settings

    from desktop_tools import cli, config

    settings = Settings(
        config.ENV_PREFIX,
        (*config.SETTINGS, Setting("test_only.secret", "", "A secret.", secret=True)),
        default_path=config.DEFAULT_CONFIG_PATH,
    )
    monkeypatch.setattr(config, "SETTINGS", settings)
    monkeypatch.setattr(cli, "SETTINGS", settings)
    return f"{config.ENV_PREFIX}TEST_ONLY_SECRET"


def test_a_set_secret_shows_set_never_its_value(
    secret_env: str, write_config: Callable[..., Path]
) -> None:
    result = runner.invoke(
        app, ["config", "-c", str(write_config(""))], env={secret_env: "hunter2"}
    )
    assert result.exit_code == 0, result.output
    assert f"test_only.secret = ******** (set)  ({secret_env})" in result.stdout
    assert "hunter2" not in result.output


def test_an_unset_secret_shows_unset(secret_env: str, write_config: Callable[..., Path]) -> None:
    result = runner.invoke(app, ["config", "-c", str(write_config(""))])
    assert result.exit_code == 0, result.output
    assert "test_only.secret = (unset)  (default)" in result.stdout


def test_main_runs_app(monkeypatch: pytest.MonkeyPatch) -> None:
    from desktop_tools import cli

    called: list[bool] = []
    monkeypatch.setattr(cli, "app", lambda: called.append(True))
    cli.main()
    assert called == [True]
