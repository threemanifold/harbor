"""Tests for :mod:`harbor.config.modal_config`."""

from __future__ import annotations

import pytest

from harbor.config.modal_config import (
    ModalConfig,
    ModalConfigError,
    load_modal_config,
    try_load_modal_config,
)


def _minimal_env() -> dict[str, str]:
    return {
        "MODAL_TOKEN_ID": "tok-id",
        "MODAL_TOKEN_SECRET": "tok-secret",
        "MODAL_WORKSPACE": "harbor-team",
    }


def test_load_modal_config_with_required_fields_only() -> None:
    config = load_modal_config(_minimal_env())
    assert config == ModalConfig(
        token_id="tok-id",
        token_secret="tok-secret",
        workspace="harbor-team",
        web_url_3b=None,
        web_url_7b=None,
        hf_token=None,
    )


def test_load_modal_config_with_optional_fields() -> None:
    env = _minimal_env() | {
        "MODAL_WEB_URL_3B": "https://harbor--qwen-3b.modal.run",
        "MODAL_WEB_URL_7B": "https://harbor--qwen-7b.modal.run",
        "HF_TOKEN": "hf_abc",
    }
    config = load_modal_config(env)
    assert config.web_url_3b == "https://harbor--qwen-3b.modal.run"
    assert config.web_url_7b == "https://harbor--qwen-7b.modal.run"
    assert config.hf_token == "hf_abc"


@pytest.mark.parametrize(
    "missing", ["MODAL_TOKEN_ID", "MODAL_TOKEN_SECRET", "MODAL_WORKSPACE"]
)
def test_load_modal_config_missing_required_raises(missing: str) -> None:
    env = _minimal_env()
    del env[missing]
    with pytest.raises(ModalConfigError) as exc_info:
        load_modal_config(env)
    assert missing in str(exc_info.value)


def test_load_modal_config_blank_values_treated_as_missing() -> None:
    env = _minimal_env() | {"MODAL_TOKEN_ID": "   "}
    with pytest.raises(ModalConfigError) as exc_info:
        load_modal_config(env)
    assert "MODAL_TOKEN_ID" in str(exc_info.value)


def test_try_load_modal_config_returns_none_for_blank_env() -> None:
    assert try_load_modal_config({}) is None


def test_try_load_modal_config_returns_config_when_set() -> None:
    config = try_load_modal_config(_minimal_env())
    assert config is not None
    assert config.workspace == "harbor-team"


def test_try_load_modal_config_partial_env_still_raises() -> None:
    # If some Modal vars are set but required ones are blank, surface the
    # error rather than silently returning None.
    env = {"MODAL_TOKEN_ID": "id"}  # missing secret + workspace
    with pytest.raises(ModalConfigError):
        try_load_modal_config(env)


def test_optional_fields_blank_strings_become_none() -> None:
    env = _minimal_env() | {
        "MODAL_WEB_URL_3B": "",
        "MODAL_WEB_URL_7B": "   ",
        "HF_TOKEN": "",
    }
    config = load_modal_config(env)
    assert config.web_url_3b is None
    assert config.web_url_7b is None
    assert config.hf_token is None
