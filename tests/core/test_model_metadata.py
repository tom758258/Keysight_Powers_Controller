from __future__ import annotations

import json

from powers_tool_core import capabilities
from powers_tool_core.model_metadata import (
    planning_profile_metadata,
    product_active_model_metadata,
)
from powers_tool_core.support_policy import (
    EXEMPT_LIVE_DIAGNOSTIC_COMMANDS,
    PURE_OFFLINE_COMMANDS,
    unevaluated_live_support_policy_metadata,
)


def test_product_active_output_control_scope_metadata_is_model_aware() -> None:
    metadata = product_active_model_metadata(())

    assert {
        model_id: profile["output_control_scope"]
        for model_id, profile in metadata.items()
    } == {
        "keysight-e36312a": "per_channel",
        "keysight-edu36311a": "per_channel",
        "keysight-e3646a": "global",
    }


def test_generic_planning_profile_metadata_is_complete_and_nonphysical() -> None:
    commands = {"set", "trigger-list", "clear", "error", "safety inspect"}

    profiles = planning_profile_metadata(commands)

    assert set(profiles) == {"generic-scpi"}
    profile = profiles["generic-scpi"]
    assert profile["profile_id"] == "generic-scpi"
    assert profile["channels"] == [1]
    assert profile["output_control_scope"] == "unknown"
    assert set(profile) == {
        "profile_id",
        "channels",
        "output_control_scope",
        "command_support",
        "live_support",
    }
    assert not {
        "model_id",
        "vendor_id",
        "driver",
        "electrical_ratings",
        "setpoint_ranges",
    } & set(profile)
    assert "generic-scpi" not in product_active_model_metadata(())

    support = profile["command_support"]
    assert set(support) == commands
    generic_support = capabilities.planning_identity_command_support(
        None,
        planning_profile_id="generic-scpi",
    )
    for command in {"set", "trigger-list", "safety inspect"}:
        expected = dict(generic_support[command])
        if expected["real"] is False:
            expected["disabled_reason"] = capabilities.unsupported_command_reason(
                command,
                "generic-scpi",
            )
        assert support[command] == expected
    for command in {"clear", "error"}:
        assert support[command] == {
            "real": True,
            "simulate": True,
            "dry_run": False,
            "requires_confirm": False,
            "hardware_validation": "model_independent",
        }

    expected_live_support = unevaluated_live_support_policy_metadata(
        commands=commands,
        reason="generic-scpi is a no-hardware planning profile.",
    )
    live_support = profile["live_support"]
    assert live_support == expected_live_support
    assert live_support["schema_version"] == 2
    assert live_support["evaluated"] is False
    assert live_support["model_id"] is None
    assert live_support["live_capable"] is False
    assert live_support["fallback_only"] is True
    assert live_support["reason"] == "generic-scpi is a no-hardware planning profile."
    assert EXEMPT_LIVE_DIAGNOSTIC_COMMANDS <= set(live_support["commands"])
    assert PURE_OFFLINE_COMMANDS <= set(live_support["commands"])
    for command in EXEMPT_LIVE_DIAGNOSTIC_COMMANDS:
        assert live_support["commands"][command]["policy_exempt"] is True
        assert live_support["commands"][command]["offline_only"] is False
    for command in PURE_OFFLINE_COMMANDS:
        assert live_support["commands"][command]["offline_only"] is True
    serialized_live_support = json.dumps(live_support)
    for field in ("transport_scope", "backend_scope", "policy_mode"):
        assert f'"{field}"' not in serialized_live_support


def test_generic_planning_profile_metadata_returns_defensive_copies() -> None:
    first = planning_profile_metadata({"set"})
    second = planning_profile_metadata({"set"})

    first["generic-scpi"]["channels"].append(2)
    first["generic-scpi"]["command_support"]["set"]["disabled_reason"] = "mutated"
    first["generic-scpi"]["live_support"]["commands"]["set"]["support_reason"] = "mutated"

    profile = second["generic-scpi"]
    assert profile["channels"] == [1]
    assert profile["command_support"]["set"]["disabled_reason"] != "mutated"
    assert profile["live_support"]["commands"]["set"]["support_reason"] != "mutated"
