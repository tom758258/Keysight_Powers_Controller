import math

import pytest

from powers_tool_core.errors import PowersToolError
from powers_tool_core.safety import (
    SafetyConfigError,
    SafetyLimits,
    SafetyValidationError,
    confirmation_required_for_setpoint,
    load_safety_config,
    validate_channel,
    validate_current,
    validate_setpoint,
    validate_voltage,
)


def test_voltage_rejects_negative_inf_and_nan() -> None:
    with pytest.raises(SafetyValidationError, match="voltage must be non-negative"):
        validate_voltage(-0.1)
    with pytest.raises(SafetyValidationError, match="voltage must be finite"):
        validate_voltage(math.inf)
    with pytest.raises(SafetyValidationError, match="voltage must be finite"):
        validate_voltage(math.nan)


def test_current_rejects_negative_inf_and_nan() -> None:
    with pytest.raises(SafetyValidationError, match="current must be non-negative"):
        validate_current(-0.1)
    with pytest.raises(SafetyValidationError, match="current must be finite"):
        validate_current(math.inf)
    with pytest.raises(SafetyValidationError, match="current must be finite"):
        validate_current(math.nan)


def test_explicit_max_limits_are_enforced() -> None:
    limits = SafetyLimits(max_voltage=5.0, max_current=0.5)

    validate_voltage(5.0, limits)
    validate_current(0.5, limits)

    with pytest.raises(SafetyValidationError, match="voltage 5.1 exceeds maximum 5"):
        validate_voltage(5.1, limits)
    with pytest.raises(SafetyValidationError, match="current 0.6 exceeds maximum 0.5"):
        validate_current(0.6, limits)


def test_no_max_limits_means_no_rating_assumption() -> None:
    validate_voltage(1_000.0, SafetyLimits())
    validate_current(100.0, SafetyLimits())


def test_allowed_channels_only_checked_when_configured() -> None:
    validate_channel(99, SafetyLimits())
    validate_channel(1, SafetyLimits(allowed_channels=(1, 2)))

    with pytest.raises(SafetyValidationError, match="channel 3 is not allowed"):
        validate_channel(3, SafetyLimits(allowed_channels=(1, 2)))


def test_validate_setpoint_checks_channel_voltage_and_current() -> None:
    limits = SafetyLimits(max_voltage=3.3, max_current=0.1, allowed_channels=(1,))

    validate_setpoint(channel=1, voltage=3.3, current=0.1, limits=limits)

    with pytest.raises(SafetyValidationError, match="channel 2 is not allowed"):
        validate_setpoint(channel=2, voltage=1.0, current=0.05, limits=limits)
    with pytest.raises(SafetyValidationError, match="voltage 4 exceeds maximum 3.3"):
        validate_setpoint(channel=1, voltage=4.0, current=0.05, limits=limits)
    with pytest.raises(SafetyValidationError, match="current 0.2 exceeds maximum 0.1"):
        validate_setpoint(channel=1, voltage=1.0, current=0.2, limits=limits)


def test_confirm_thresholds_are_advisory_below_hard_max() -> None:
    limits = SafetyLimits(
        max_voltage=5.0,
        max_current=0.5,
        confirm_above_voltage=1.0,
        confirm_above_current=0.1,
    )

    validate_setpoint(channel=1, voltage=2.0, current=0.2, limits=limits)
    assert confirmation_required_for_setpoint(voltage=2.0, current=0.2, limits=limits) is True
    assert confirmation_required_for_setpoint(voltage=1.0, current=0.1, limits=limits) is False


def test_safety_error_type_matches_project_and_value_errors() -> None:
    error = SafetyValidationError("bad setpoint")

    assert isinstance(error, PowersToolError)
    assert isinstance(error, ValueError)


def test_load_safety_config_returns_limits(tmp_path) -> None:
    config_path = tmp_path / "powers-tool.toml"
    config_path.write_text(
        """
[safety]
max_voltage = 5.0
max_current = 0.5
confirm_above_voltage = 3.3
allowed_channels = [1, 2, 3]
""".strip(),
        encoding="utf-8",
    )

    limits = load_safety_config(config_path)

    assert limits == SafetyLimits(
        max_voltage=5.0,
        max_current=0.5,
        confirm_above_voltage=3.3,
        allowed_channels=(1, 2, 3),
    )


def test_load_safety_config_resolves_resource_alias_with_field_overrides(tmp_path) -> None:
    config_path = tmp_path / "powers-tool.toml"
    config_path.write_text(
        """
[safety]
max_voltage = 5.0
max_current = 0.5
allowed_channels = [1, 2]

[[resources]]
alias = "sim-e36312a"
resource = "USB0::SIM::E36312A::INSTR"
max_voltage = 3.3
allowed_channels = [1]
""".strip(),
        encoding="utf-8",
    )

    limits = load_safety_config(config_path, resource_alias="sim-e36312a")

    assert limits == SafetyLimits(
        max_voltage=3.3,
        max_current=0.5,
        allowed_channels=(1,),
    )


def test_load_safety_config_resolves_raw_resource_matches(tmp_path) -> None:
    config_path = tmp_path / "powers-tool.toml"
    config_path.write_text(
        """
[safety]
max_voltage = 5.0
max_current = 0.5
allowed_channels = [1, 2]

[[resources]]
alias = "sim-e36312a"
resource = "USB0::SIM::E36312A::INSTR"
max_current = 0.1
""".strip(),
        encoding="utf-8",
    )

    limits = load_safety_config(
        config_path,
        resource="USB0::SIM::E36312A::INSTR",
    )

    assert limits == SafetyLimits(
        max_voltage=5.0,
        max_current=0.1,
        allowed_channels=(1, 2),
    )


def test_load_safety_config_raw_resource_falls_back_to_global_limits(tmp_path) -> None:
    config_path = tmp_path / "powers-tool.toml"
    config_path.write_text(
        """
[safety]
max_voltage = 5.0
max_current = 0.5

[[resources]]
alias = "sim-e36312a"
resource = "USB0::SIM::E36312A::INSTR"
max_voltage = 3.3
""".strip(),
        encoding="utf-8",
    )

    limits = load_safety_config(config_path, resource="USB0::OTHER::INSTR")

    assert limits == SafetyLimits(max_voltage=5.0, max_current=0.5)


def test_load_safety_config_rejects_unknown_resource_alias(tmp_path) -> None:
    config_path = tmp_path / "powers-tool.toml"
    config_path.write_text(
        """
[safety]
max_voltage = 5.0

[[resources]]
alias = "sim-e36312a"
resource = "USB0::SIM::E36312A::INSTR"
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(SafetyConfigError, match="unknown resource alias: missing"):
        load_safety_config(config_path, resource_alias="missing")


def test_load_safety_config_rejects_missing_file(tmp_path) -> None:
    with pytest.raises(SafetyConfigError, match="safety config not found"):
        load_safety_config(tmp_path / "missing.toml")


def test_load_safety_config_rejects_invalid_toml(tmp_path) -> None:
    config_path = tmp_path / "powers-tool.toml"
    config_path.write_text("[safety\n", encoding="utf-8")

    with pytest.raises(SafetyConfigError, match="could not parse safety config"):
        load_safety_config(config_path)


@pytest.mark.parametrize(
    ("content", "expected_message"),
    [
        ("[other]\nmax_voltage = 5.0\n", "unsupported safety config key: other"),
        ("[safety]\n", "must define at least one supported field"),
        ("[safety]\nmodel = 'E36312A'\n", "unsupported \\[safety\\] key: model"),
    ],
)
def test_load_safety_config_rejects_schema_errors(
    tmp_path,
    content,
    expected_message,
) -> None:
    config_path = tmp_path / "powers-tool.toml"
    config_path.write_text(content, encoding="utf-8")

    with pytest.raises(SafetyConfigError, match=expected_message):
        load_safety_config(config_path)


@pytest.mark.parametrize(
    ("content", "expected_message"),
    [
        (
            """
[safety]
max_voltage = 5.0

[[resources]]
resource = "USB0::SIM::E36312A::INSTR"
""".strip(),
            "resources entry 1 must define non-empty alias",
        ),
        (
            """
[safety]
max_voltage = 5.0

[[resources]]
alias = "sim-e36312a"
""".strip(),
            "resources entry 1 must define non-empty resource",
        ),
        (
            """
[safety]
max_voltage = 5.0

[[resources]]
alias = "dup"
resource = "USB0::A::INSTR"

[[resources]]
alias = "dup"
resource = "USB0::B::INSTR"
""".strip(),
            "duplicate resource alias: dup",
        ),
        (
            """
[safety]
max_voltage = 5.0

[[resources]]
alias = "a"
resource = "USB0::A::INSTR"

[[resources]]
alias = "b"
resource = "USB0::A::INSTR"
""".strip(),
            "duplicate resource string: USB0::A::INSTR",
        ),
        (
            """
[safety]
max_voltage = 5.0

[[resources]]
alias = "sim-e36312a"
resource = "USB0::SIM::E36312A::INSTR"
model = "E36312A"
""".strip(),
            "unsupported resources entry key: model",
        ),
        (
            """
[safety]
max_voltage = 5.0

[[resources]]
alias = "sim-e36312a"
resource = "USB0::SIM::E36312A::INSTR"
max_current = -0.1
""".strip(),
            "max_current must be non-negative",
        ),
    ],
)
def test_load_safety_config_rejects_resource_entry_errors(
    tmp_path,
    content,
    expected_message,
) -> None:
    config_path = tmp_path / "powers-tool.toml"
    config_path.write_text(content, encoding="utf-8")

    with pytest.raises(SafetyConfigError, match=expected_message):
        load_safety_config(config_path)


@pytest.mark.parametrize(
    ("field", "value", "expected_message"),
    [
        ("max_voltage", "-0.1", "max_voltage must be non-negative"),
        ("max_voltage", "nan", "max_voltage must be finite"),
        ("max_voltage", "inf", "max_voltage must be finite"),
        ("max_voltage", "'5'", "max_voltage must be a finite non-negative number"),
        ("max_current", "-0.1", "max_current must be non-negative"),
        ("max_current", "nan", "max_current must be finite"),
        ("max_current", "inf", "max_current must be finite"),
        ("max_current", "true", "max_current must be a finite non-negative number"),
    ],
)
def test_load_safety_config_rejects_invalid_numeric_limits(
    tmp_path,
    field,
    value,
    expected_message,
) -> None:
    config_path = tmp_path / "powers-tool.toml"
    config_path.write_text(f"[safety]\n{field} = {value}\n", encoding="utf-8")

    with pytest.raises(SafetyConfigError, match=expected_message):
        load_safety_config(config_path)


@pytest.mark.parametrize(
    "value",
    [
        "'1'",
        "[0]",
        "[-1]",
        "[1.5]",
        "['1']",
        "[true]",
    ],
)
def test_load_safety_config_rejects_invalid_allowed_channels(tmp_path, value) -> None:
    config_path = tmp_path / "powers-tool.toml"
    config_path.write_text(f"[safety]\nallowed_channels = {value}\n", encoding="utf-8")

    with pytest.raises(
        SafetyConfigError,
        match="allowed_channels must be a list of positive integers",
    ):
        load_safety_config(config_path)
