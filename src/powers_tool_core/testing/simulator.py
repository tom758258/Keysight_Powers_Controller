"""Deterministic simulator resources for CLI and driver tests."""

from __future__ import annotations

import copy
import re

from powers_tool_core.errors import VisaConnectionError

SIMULATED_RESOURCES = (
    "USB0::SIM::E36312A::INSTR",
    "USB0::SIM::EDU36311A::INSTR",
    "ASRL1::SIM::E3646A::INSTR",
    "ASRL1::SIM::PSM2010::INSTR",
)

SIMULATED_IDN = {
    "USB0::SIM::E36312A::INSTR": "KEYSIGHT,E36312A,SIM000003,1.0",
    "USB0::SIM::EDU36311A::INSTR": "KEYSIGHT,EDU36311A,SIM000004,1.0",
    "ASRL1::SIM::E3646A::INSTR": "KEYSIGHT,E3646A,SIM000005,1.0",
    "ASRL1::SIM::PSM2010::INSTR": "GW.Inc,PSM-2010,SIM000006,FW1.00",
}

SIMULATED_MEASUREMENTS = {
    "USB0::SIM::E36312A::INSTR": {
        1: {"voltage": "1.100", "current": "0.110"},
        2: {"voltage": "2.200", "current": "0.220"},
        3: {"voltage": "3.300", "current": "0.330"},
    },
    "USB0::SIM::EDU36311A::INSTR": {
        1: {"voltage": "1.010", "current": "0.101"},
        2: {"voltage": "2.020", "current": "0.202"},
        3: {"voltage": "3.030", "current": "0.303"},
    },
    "ASRL1::SIM::E3646A::INSTR": {
        1: {"voltage": "1.460", "current": "0.146"},
        2: {"voltage": "2.460", "current": "0.246"},
    },
    "ASRL1::SIM::PSM2010::INSTR": {
        1: {"voltage": "1.000", "current": "0.050"},
    },
}

SIMULATED_OUTPUT_STATES = {
    "USB0::SIM::E36312A::INSTR": {1: False, 2: False, 3: False},
    "USB0::SIM::EDU36311A::INSTR": {1: False, 2: False, 3: False},
    "ASRL1::SIM::E3646A::INSTR": {1: False, 2: False},
    "ASRL1::SIM::PSM2010::INSTR": {1: False},
}

SIMULATED_PROGRAMMED_SETPOINTS = {
    "USB0::SIM::E36312A::INSTR": {
        1: {"voltage": "1.000", "current": "0.050"},
        2: {"voltage": "2.000", "current": "0.100"},
        3: {"voltage": "3.000", "current": "0.150"},
    },
    "USB0::SIM::EDU36311A::INSTR": {
        1: {"voltage": "1.000", "current": "0.050"},
        2: {"voltage": "2.000", "current": "0.100"},
        3: {"voltage": "3.000", "current": "0.150"},
    },
    "ASRL1::SIM::E3646A::INSTR": {
        1: {"voltage": "1.000", "current": "0.050"},
        2: {"voltage": "2.000", "current": "0.100"},
    },
    "ASRL1::SIM::PSM2010::INSTR": {
        1: {"voltage": "1.000", "current": "0.050"},
    },
}

SIMULATED_OUTPUT_RANGES = {
    "ASRL1::SIM::PSM2010::INSTR": "P8V",
}

SIMULATED_OPTIONS = {
    "USB0::SIM::E36312A::INSTR": "0",
}

SIMULATED_SCPI_VERSION = {
    "USB0::SIM::E36312A::INSTR": "1999.0",
}

SIMULATED_REMOTE_LOCKOUT = {
    "USB0::SIM::E36312A::INSTR": "RWLock",
}

SIMULATED_PROTECTION_TRIPS = {
    "USB0::SIM::E36312A::INSTR": {
        1: {"voltage": False, "current": False},
        2: {"voltage": False, "current": False},
        3: {"voltage": False, "current": False},
    },
    "ASRL1::SIM::PSM2010::INSTR": {
        1: {"voltage": False, "current": False},
    },
    "USB0::SIM::EDU36311A::INSTR": {
        1: {"voltage": False, "current": False},
        2: {"voltage": False, "current": False},
        3: {"voltage": False, "current": False},
    },
}

SIMULATED_PROTECTION_SETTINGS = {
    "USB0::SIM::E36312A::INSTR": {
        1: {"ovp_voltage": "6.000", "ocp_enabled": "ON", "ocp_delay": "0.08", "ocp_delay_trigger": "SCH"},
        2: {"ovp_voltage": "6.000", "ocp_enabled": "ON", "ocp_delay": "0.08", "ocp_delay_trigger": "SCH"},
        3: {"ovp_voltage": "6.000", "ocp_enabled": "ON", "ocp_delay": "0.08", "ocp_delay_trigger": "SCH"},
    },
    "ASRL1::SIM::PSM2010::INSTR": {
        1: {
            "ovp_voltage": "21.000",
            "ocp_enabled": "ON",
            "ocp_delay": "0.1",
            "ocp_delay_trigger": None,
        },
    },
    "USB0::SIM::EDU36311A::INSTR": {
        1: {"ovp_voltage": "6.000", "ocp_enabled": "ON", "ocp_delay": "0.08", "ocp_delay_trigger": "SCH"},
        2: {"ovp_voltage": "6.000", "ocp_enabled": "ON", "ocp_delay": "0.08", "ocp_delay_trigger": "SCH"},
        3: {"ovp_voltage": "6.000", "ocp_enabled": "ON", "ocp_delay": "0.08", "ocp_delay_trigger": "SCH"},
    },
}

SIMULATED_DIGITAL_PINS = {
    "USB0::SIM::E36312A::INSTR": {
        1: {"function": "DIO", "polarity": "POS"},
        2: {"function": "DIO", "polarity": "POS"},
        3: {"function": "DIO", "polarity": "POS"},
    },
}

SIMULATED_TRIGGER_STATE = {
    "USB0::SIM::E36312A::INSTR": {
        1: {
            "source": "BUS",
            "delay": "0",
            "voltage_mode": "STEP",
            "current_mode": "STEP",
            "triggered_voltage": "1.000",
            "triggered_current": "0.050",
            "armed": False,
        },
        2: {
            "source": "BUS",
            "delay": "0",
            "voltage_mode": "STEP",
            "current_mode": "STEP",
            "triggered_voltage": "2.000",
            "triggered_current": "0.100",
            "armed": False,
        },
        3: {
            "source": "BUS",
            "delay": "0",
            "voltage_mode": "STEP",
            "current_mode": "STEP",
            "triggered_voltage": "3.000",
            "triggered_current": "0.150",
            "armed": False,
        },
        "trigger_output_bus": False,
    },
    "USB0::SIM::EDU36311A::INSTR": {
        1: {
            "source": "BUS",
            "delay": "0",
            "voltage_mode": "STEP",
            "current_mode": "STEP",
            "triggered_voltage": "1.000",
            "triggered_current": "0.050",
            "armed": False,
        },
        2: {
            "source": "BUS",
            "delay": "0",
            "voltage_mode": "STEP",
            "current_mode": "STEP",
            "triggered_voltage": "2.000",
            "triggered_current": "0.100",
            "armed": False,
        },
        3: {
            "source": "BUS",
            "delay": "0",
            "voltage_mode": "STEP",
            "current_mode": "STEP",
            "triggered_voltage": "3.000",
            "triggered_current": "0.150",
            "armed": False,
        },
        "trigger_output_bus": False,
    },
}

SIMULATED_LIST_STATE = {
    "USB0::SIM::E36312A::INSTR": {
        1: {
            "voltage": ["1.000"],
            "current": ["0.050"],
            "dwell": ["0.01"],
            "tout_bost": ["0"],
            "tout_eost": ["0"],
            "count": "1",
            "step": "AUTO",
            "terminate_last": "ON",
        },
        2: {
            "voltage": ["2.000"],
            "current": ["0.100"],
            "dwell": ["0.01"],
            "tout_bost": ["0"],
            "tout_eost": ["0"],
            "count": "1",
            "step": "AUTO",
            "terminate_last": "ON",
        },
        3: {
            "voltage": ["3.000"],
            "current": ["0.150"],
            "dwell": ["0.01"],
            "tout_bost": ["0"],
            "tout_eost": ["0"],
            "count": "1",
            "step": "AUTO",
            "terminate_last": "ON",
        },
    },
}

SIMULATED_STATUS_STATE = {
    resource: {"ese": 0, "esr": 0}
    for resource in SIMULATED_IDN
}

_DEFAULT_OUTPUT_STATES = copy.deepcopy(SIMULATED_OUTPUT_STATES)
_DEFAULT_PROGRAMMED_SETPOINTS = copy.deepcopy(SIMULATED_PROGRAMMED_SETPOINTS)
_DEFAULT_OUTPUT_RANGES = copy.deepcopy(SIMULATED_OUTPUT_RANGES)
_DEFAULT_PROTECTION_TRIPS = copy.deepcopy(SIMULATED_PROTECTION_TRIPS)
_DEFAULT_PROTECTION_SETTINGS = copy.deepcopy(SIMULATED_PROTECTION_SETTINGS)
_DEFAULT_DIGITAL_PINS = copy.deepcopy(SIMULATED_DIGITAL_PINS)
_DEFAULT_TRIGGER_STATE = copy.deepcopy(SIMULATED_TRIGGER_STATE)
_DEFAULT_LIST_STATE = copy.deepcopy(SIMULATED_LIST_STATE)
_DEFAULT_STATUS_STATE = copy.deepcopy(SIMULATED_STATUS_STATE)


def _reset_simulated_state() -> None:
    global SIMULATED_OUTPUT_STATES
    global SIMULATED_PROGRAMMED_SETPOINTS
    global SIMULATED_OUTPUT_RANGES
    global SIMULATED_PROTECTION_TRIPS
    global SIMULATED_PROTECTION_SETTINGS
    global SIMULATED_DIGITAL_PINS
    global SIMULATED_TRIGGER_STATE
    global SIMULATED_LIST_STATE
    global SIMULATED_STATUS_STATE

    SIMULATED_OUTPUT_STATES = copy.deepcopy(_DEFAULT_OUTPUT_STATES)
    SIMULATED_PROGRAMMED_SETPOINTS = copy.deepcopy(_DEFAULT_PROGRAMMED_SETPOINTS)
    SIMULATED_OUTPUT_RANGES = copy.deepcopy(_DEFAULT_OUTPUT_RANGES)
    SIMULATED_PROTECTION_TRIPS = copy.deepcopy(_DEFAULT_PROTECTION_TRIPS)
    SIMULATED_PROTECTION_SETTINGS = copy.deepcopy(_DEFAULT_PROTECTION_SETTINGS)
    SIMULATED_DIGITAL_PINS = copy.deepcopy(_DEFAULT_DIGITAL_PINS)
    SIMULATED_TRIGGER_STATE = copy.deepcopy(_DEFAULT_TRIGGER_STATE)
    SIMULATED_LIST_STATE = copy.deepcopy(_DEFAULT_LIST_STATE)
    SIMULATED_STATUS_STATE = copy.deepcopy(_DEFAULT_STATUS_STATE)


class SimulatedResourceManager:
    """Resource manager that never opens real VISA resources."""

    def __init__(self, resources: tuple[str, ...] = SIMULATED_RESOURCES) -> None:
        _reset_simulated_state()
        self._resources = resources

    def list_resources(self) -> tuple[str, ...]:
        return self._resources

    def open_resource(self, resource_name: str) -> "SimulatedResource":
        if resource_name not in SIMULATED_IDN:
            raise VisaConnectionError(f"Unknown simulated resource {resource_name!r}")
        return SimulatedResource(resource_name)


class SimulatedResource:
    """Small PyVISA-like resource for deterministic no-hardware flows."""

    def __init__(self, resource_name: str) -> None:
        self.resource_name = resource_name
        self.timeout: int | None = None
        self.read_termination: str | None = None
        self.write_termination: str | None = None
        self.commands: list[str] = []
        self.closed = False
        self.selected_channel = 1

    def write(self, command: str) -> None:
        self._ensure_open()
        self.commands.append(command)
        if command.startswith("INST:NSEL "):
            channel = int(float(command.removeprefix("INST:NSEL ").strip()))
            if channel not in SIMULATED_OUTPUT_STATES.get(self.resource_name, {}):
                raise VisaConnectionError(f"No simulated response for {command!r}")
            self.selected_channel = channel
            return
        if command in {"SYST:REM", "SYST:LOC"}:
            return
        if command in {"VOLT:RANG LOW", "VOLT:RANG HIGH"}:
            if self.resource_name not in SIMULATED_OUTPUT_RANGES:
                raise VisaConnectionError(f"No simulated response for {command!r}")
            SIMULATED_OUTPUT_RANGES[self.resource_name] = (
                "P8V" if command.endswith(" LOW") else "P20V"
            )
            return
        if _simulated_status_write(self.resource_name, command):
            return
        if _simulated_trigger_write(self.resource_name, command):
            return
        output_change = _simulated_output_change(command)
        if output_change is not None:
            channel, enabled = output_change
            if channel == 0:
                channel = self.selected_channel
            if channel not in SIMULATED_OUTPUT_STATES.get(self.resource_name, {}):
                raise VisaConnectionError(f"No simulated response for {command!r}")
            SIMULATED_OUTPUT_STATES[self.resource_name][channel] = enabled
            return
        setpoint_change = _simulated_setpoint_change(command)
        if setpoint_change is not None:
            name, channel, value = setpoint_change
            if channel == 0:
                channel = self.selected_channel
            if channel not in SIMULATED_PROGRAMMED_SETPOINTS.get(self.resource_name, {}):
                raise VisaConnectionError(f"No simulated response for {command!r}")
            SIMULATED_PROGRAMMED_SETPOINTS[self.resource_name][channel][name] = value
            return
        if _simulated_clear_protection(self.resource_name, command) is not None:
            return
        if _simulated_protection_set(self.resource_name, command) is not None:
            return

    def query(self, command: str) -> str:
        self._ensure_open()
        self.commands.append(command)
        if command == "*IDN?":
            return SIMULATED_IDN[self.resource_name]
        if command == "SYST:ERR?":
            return '0,"No error"'
        if command == "VOLT:RANG?":
            try:
                return SIMULATED_OUTPUT_RANGES[self.resource_name]
            except KeyError as exc:
                raise VisaConnectionError(f"No simulated response for {command!r}") from exc
        if command == "MEAS?" and self.resource_name in SIMULATED_OUTPUT_RANGES:
            return SIMULATED_MEASUREMENTS[self.resource_name][1]["voltage"]
        if command == "INST:NSEL?":
            return str(self.selected_channel)
        if command == "*OPT?":
            return SIMULATED_OPTIONS.get(self.resource_name, "0")
        if command == "SYST:VERS?":
            return SIMULATED_SCPI_VERSION.get(self.resource_name, "1999.0")
        if command == "SYST:COMM:RLST?":
            return SIMULATED_REMOTE_LOCKOUT.get(self.resource_name, "RWLock")
        protection_trip = _simulated_protection_trip(self.resource_name, command)
        if protection_trip is not None:
            return "1" if protection_trip else "0"
        if command == "*OPC?":
            return "1"
        if command == "*ESR?":
            state = SIMULATED_STATUS_STATE[self.resource_name]
            value = state["esr"]
            state["esr"] = 0
            return str(value)
        trigger_response = _simulated_trigger_query(self.resource_name, command)
        if trigger_response is not None:
            return trigger_response
        protection_setting = _simulated_protection_setting(command)
        if protection_setting is not None:
            name, channel = protection_setting
            try:
                return SIMULATED_PROTECTION_SETTINGS[self.resource_name][channel][name]
            except KeyError as exc:
                raise VisaConnectionError(f"No simulated response for {command!r}") from exc
        output_state = _simulated_output_state(command)
        if output_state is not None:
            channel = self.selected_channel if output_state == 0 else output_state
            try:
                return "ON" if SIMULATED_OUTPUT_STATES[self.resource_name][channel] else "OFF"
            except KeyError as exc:
                raise VisaConnectionError(f"No simulated response for {command!r}") from exc
        measurement = _simulated_measurement(command)
        if measurement is not None:
            measurement_name, channel = measurement
            if channel == 0:
                channel = self.selected_channel
            try:
                return SIMULATED_MEASUREMENTS[self.resource_name][channel][measurement_name]
            except KeyError as exc:
                raise VisaConnectionError(f"No simulated response for {command!r}") from exc
        setpoint = _simulated_setpoint(command)
        if setpoint is not None:
            setpoint_name, channel = setpoint
            if channel == 0:
                channel = self.selected_channel
            try:
                return SIMULATED_PROGRAMMED_SETPOINTS[self.resource_name][channel][setpoint_name]
            except KeyError as exc:
                raise VisaConnectionError(f"No simulated response for {command!r}") from exc
        raise VisaConnectionError(f"No simulated response for {command!r}")

    def close(self) -> None:
        self.closed = True

    def read_stb(self) -> int:
        self._ensure_open()
        state = SIMULATED_STATUS_STATE[self.resource_name]
        return 32 if state["esr"] & state["ese"] else 0

    def _ensure_open(self) -> None:
        if self.closed:
            raise VisaConnectionError("Simulated resource is closed")


def _simulated_measurement(command: str) -> tuple[str, int] | None:
    if command == "MEAS:VOLT?":
        return ("voltage", 0)
    if command == "MEAS:CURR?":
        return ("current", 0)
    if command.startswith("MEAS:VOLT? (@") and command.endswith(")"):
        return ("voltage", _parse_channel_list(command, "MEAS:VOLT? (@"))
    if command.startswith("MEAS:CURR? (@") and command.endswith(")"):
        return ("current", _parse_channel_list(command, "MEAS:CURR? (@"))
    return None


def _simulated_setpoint(command: str) -> tuple[str, int] | None:
    if command == "VOLT?":
        return ("voltage", 0)
    if command == "CURR?":
        return ("current", 0)
    if command.startswith("VOLT? (@") and command.endswith(")"):
        return ("voltage", _parse_channel_list(command, "VOLT? (@"))
    if command.startswith("CURR? (@") and command.endswith(")"):
        return ("current", _parse_channel_list(command, "CURR? (@"))
    return None


def _simulated_setpoint_change(command: str) -> tuple[str, int, str] | None:
    if command.startswith("VOLT ") and ",(@" in command and command.endswith(")"):
        value, channel_text = command.removeprefix("VOLT ").split(",(@", maxsplit=1)
        return ("voltage", _parse_channel_list(f"(@{channel_text}", "(@"), value)
    if command.startswith("CURR ") and ",(@" in command and command.endswith(")"):
        value, channel_text = command.removeprefix("CURR ").split(",(@", maxsplit=1)
        return ("current", _parse_channel_list(f"(@{channel_text}", "(@"), value)
    if command.startswith("VOLT ") and ",(@" not in command:
        value = command.removeprefix("VOLT ").strip()
        return ("voltage", 0, value)
    if command.startswith("CURR ") and ",(@" not in command:
        value = command.removeprefix("CURR ").strip()
        return ("current", 0, value)
    return None


def _simulated_output_change(command: str) -> tuple[int, bool] | None:
    if command.startswith("OUTP ") and ",(@" in command and command.endswith(")"):
        state, channel_text = command.removeprefix("OUTP ").split(",(@", maxsplit=1)
        if state not in {"ON", "OFF"}:
            raise VisaConnectionError(f"Unsupported simulated output command {command!r}")
        return (_parse_channel_list(f"(@{channel_text}", "(@"), state == "ON")
    if command in {"OUTP ON", "OUTP OFF"}:
        return (0, command == "OUTP ON")
    return None


def _simulated_output_state(command: str) -> int | None:
    if command == "OUTP?":
        return 0
    if command.startswith("OUTP? (@") and command.endswith(")"):
        return _parse_channel_list(command, "OUTP? (@")
    return None


def _simulated_digital_pin_function(command: str) -> bool:
    return re.fullmatch(r"DIG:PIN[123]:FUNC (?:DIO|TOUT|TINP)", command) is not None


def _simulated_digital_pin_polarity(command: str) -> bool:
    return re.fullmatch(r"DIG:PIN[123]:POL (?:POS|NEG)", command) is not None


def _simulated_clear_protection(resource_name: str, command: str) -> int | None:
    if command.startswith("OUTP:PROT:CLE (@") and command.endswith(")"):
        channel = _parse_channel_list(command, "OUTP:PROT:CLE (@")
        SIMULATED_PROTECTION_TRIPS[resource_name][channel] = {
            "voltage": False,
            "current": False,
        }
        return channel
    if command in {"CURR:PROT:CLE", "VOLT:PROT:CLE"}:
        trip = "current" if command.startswith("CURR") else "voltage"
        SIMULATED_PROTECTION_TRIPS[resource_name][1][trip] = False
        return 1
    return None


def _simulated_protection_set(resource_name: str, command: str) -> int | None:
    if command.startswith("VOLT:PROT ") and ",(@" not in command:
        value = command.removeprefix("VOLT:PROT ").strip()
        float(value)
        SIMULATED_PROTECTION_SETTINGS[resource_name][1]["ovp_voltage"] = value
        return 1
    if command.startswith("CURR:PROT:STAT ") and ",(@" not in command:
        state = command.removeprefix("CURR:PROT:STAT ").strip()
        if state not in {"ON", "OFF"}:
            raise VisaConnectionError(f"Unsupported simulated protection command {command!r}")
        SIMULATED_PROTECTION_SETTINGS[resource_name][1]["ocp_enabled"] = state
        return 1
    if command.startswith("CURR:PROT:DEL ") and ",(@" not in command:
        value = command.removeprefix("CURR:PROT:DEL ").strip()
        delay = float(value)
        if not 0.1 <= delay <= 10.0:
            raise VisaConnectionError(f"Unsupported simulated protection command {command!r}")
        SIMULATED_PROTECTION_SETTINGS[resource_name][1]["ocp_delay"] = value
        return 1
    if command.startswith("VOLT:PROT ") and ",(@" in command and command.endswith(")"):
        value, channel_text = command.removeprefix("VOLT:PROT ").split(",(@", maxsplit=1)
        try:
            float(value)
        except ValueError as exc:
            raise VisaConnectionError(f"Unsupported simulated protection command {command!r}") from exc
        channel = _parse_channel_list(f"(@{channel_text}", "(@")
        try:
            SIMULATED_PROTECTION_SETTINGS[resource_name][channel]["ovp_voltage"] = value
        except KeyError as exc:
            raise VisaConnectionError(f"No simulated response for {command!r}") from exc
        return channel
    if command.startswith("CURR:PROT:STAT ") and ",(@" in command and command.endswith(")"):
        state, channel_text = command.removeprefix("CURR:PROT:STAT ").split(",(@", maxsplit=1)
        if state not in {"ON", "OFF"}:
            raise VisaConnectionError(f"Unsupported simulated protection command {command!r}")
        channel = _parse_channel_list(f"(@{channel_text}", "(@")
        try:
            SIMULATED_PROTECTION_SETTINGS[resource_name][channel]["ocp_enabled"] = state
        except KeyError as exc:
            raise VisaConnectionError(f"No simulated response for {command!r}") from exc
        return channel
    if command.startswith("CURR:PROT:DEL ") and ",(@" in command and command.endswith(")"):
        value, channel_text = command.removeprefix("CURR:PROT:DEL ").split(",(@", maxsplit=1)
        try:
            delay = float(value)
        except ValueError as exc:
            raise VisaConnectionError(f"Unsupported simulated protection command {command!r}") from exc
        if delay < 0:
            raise VisaConnectionError(f"Unsupported simulated protection command {command!r}")
        channel = _parse_channel_list(f"(@{channel_text}", "(@")
        try:
            SIMULATED_PROTECTION_SETTINGS[resource_name][channel]["ocp_delay"] = value
        except KeyError as exc:
            raise VisaConnectionError(f"No simulated response for {command!r}") from exc
        return channel
    if command.startswith("CURR:PROT:DEL:STAR ") and ",(@" in command and command.endswith(")"):
        trigger, channel_text = command.removeprefix("CURR:PROT:DEL:STAR ").split(",(@", maxsplit=1)
        if trigger not in {"SCH", "CCTR"}:
            raise VisaConnectionError(f"Unsupported simulated protection command {command!r}")
        channel = _parse_channel_list(f"(@{channel_text}", "(@")
        try:
            SIMULATED_PROTECTION_SETTINGS[resource_name][channel]["ocp_delay_trigger"] = trigger
        except KeyError as exc:
            raise VisaConnectionError(f"No simulated response for {command!r}") from exc
        return channel
    return None


def _simulated_status_write(resource_name: str, command: str) -> bool:
    if resource_name not in SIMULATED_STATUS_STATE:
        return False
    if command == "*CLS":
        SIMULATED_STATUS_STATE[resource_name]["esr"] = 0
        return True
    if command.startswith("*ESE "):
        value = command.removeprefix("*ESE ").strip()
        try:
            SIMULATED_STATUS_STATE[resource_name]["ese"] = int(float(value))
        except ValueError as exc:
            raise VisaConnectionError(f"Unsupported simulated status command {command!r}") from exc
        return True
    if command == "*OPC":
        SIMULATED_STATUS_STATE[resource_name]["esr"] |= 1
        return True
    return False


def _simulated_protection_setting(command: str) -> tuple[str, int] | None:
    if command == "VOLT:PROT?":
        return ("ovp_voltage", 1)
    if command == "CURR:PROT:STAT?":
        return ("ocp_enabled", 1)
    if command == "CURR:PROT:DEL?":
        return ("ocp_delay", 1)
    if command.startswith("VOLT:PROT? (@") and command.endswith(")"):
        return ("ovp_voltage", _parse_channel_list(command, "VOLT:PROT? (@"))
    if command.startswith("CURR:PROT:STAT? (@") and command.endswith(")"):
        return ("ocp_enabled", _parse_channel_list(command, "CURR:PROT:STAT? (@"))
    if command.startswith("CURR:PROT:DEL? (@") and command.endswith(")"):
        return ("ocp_delay", _parse_channel_list(command, "CURR:PROT:DEL? (@"))
    if command.startswith("CURR:PROT:DEL:STAR? (@") and command.endswith(")"):
        return ("ocp_delay_trigger", _parse_channel_list(command, "CURR:PROT:DEL:STAR? (@"))
    return None


def _simulated_protection_trip(resource_name: str, command: str) -> bool | None:
    trip_key = None
    query = None
    if command.startswith("VOLT:PROT:TRIP?"):
        trip_key = "voltage"
        query = "VOLT:PROT:TRIP?"
    elif command.startswith("CURR:PROT:TRIP?"):
        trip_key = "current"
        query = "CURR:PROT:TRIP?"
    if trip_key is None or query is None:
        return None

    channel_trips = SIMULATED_PROTECTION_TRIPS.get(resource_name, {})
    if command == query:
        return any(state.get(trip_key, False) for state in channel_trips.values())
    prefix = f"{query} (@"
    if command.startswith(prefix) and command.endswith(")"):
        channel = _parse_channel_list(command, prefix)
        return bool(channel_trips.get(channel, {}).get(trip_key, False))
    return None


def _parse_channel_list(command: str, prefix: str) -> int:
    channel_text = command.removeprefix(prefix).removesuffix(")").strip()
    try:
        channel = int(channel_text)
    except ValueError as exc:
        raise VisaConnectionError(f"Unsupported simulated channel list in {command!r}") from exc
    if channel < 1:
        raise VisaConnectionError(f"Unsupported simulated channel list in {command!r}")
    return channel


def _simulated_trigger_write(resource_name: str, command: str) -> bool:
    if resource_name not in SIMULATED_TRIGGER_STATE:
        return False
    if command in {"*TRG", "TRIG"}:
        _execute_armed_triggers(resource_name)
        return True
    if _simulated_digital_pin_function(command):
        match = re.fullmatch(r"DIG:PIN([123]):FUNC (DIO|TOUT|TINP)", command)
        if match is None:
            return False
        pin = int(match.group(1))
        SIMULATED_DIGITAL_PINS[resource_name][pin]["function"] = match.group(2)
        return True
    if _simulated_digital_pin_polarity(command):
        match = re.fullmatch(r"DIG:PIN([123]):POL (POS|NEG)", command)
        if match is None:
            return False
        pin = int(match.group(1))
        SIMULATED_DIGITAL_PINS[resource_name][pin]["polarity"] = match.group(2)
        return True
    if command.startswith("DIG:TOUT:BUS "):
        state = command.removeprefix("DIG:TOUT:BUS ").strip()
        if state not in {"ON", "OFF"}:
            raise VisaConnectionError(f"Unsupported simulated trigger command {command!r}")
        SIMULATED_TRIGGER_STATE[resource_name]["trigger_output_bus"] = state == "ON"
        return True
    trigger_setpoint = _simulated_trigger_setpoint_change(command)
    if trigger_setpoint is not None:
        kind, channel, value = trigger_setpoint
        key = "triggered_voltage" if kind == "voltage" else "triggered_current"
        SIMULATED_TRIGGER_STATE[resource_name][channel][key] = value
        return True
    trigger_mode = _simulated_trigger_mode_change(command)
    if trigger_mode is not None:
        kind, channel, mode = trigger_mode
        key = "voltage_mode" if kind == "voltage" else "current_mode"
        SIMULATED_TRIGGER_STATE[resource_name][channel][key] = mode
        return True
    trigger_source = _simulated_trigger_source_change(command)
    if trigger_source is not None:
        channel, source = trigger_source
        SIMULATED_TRIGGER_STATE[resource_name][channel]["source"] = source
        return True
    trigger_delay = _simulated_trigger_delay_change(command)
    if trigger_delay is not None:
        channel, delay = trigger_delay
        SIMULATED_TRIGGER_STATE[resource_name][channel]["delay"] = delay
        return True
    channel = _simulated_init_or_abort(command, "INIT")
    if channel is not None:
        SIMULATED_TRIGGER_STATE[resource_name][channel]["armed"] = True
        if SIMULATED_TRIGGER_STATE[resource_name][channel]["source"] == "IMM":
            _execute_trigger(resource_name, channel)
        return True
    channel = _simulated_init_or_abort(command, "ABOR")
    if channel is not None:
        SIMULATED_TRIGGER_STATE[resource_name][channel]["armed"] = False
        return True
    list_change = _simulated_list_change(command)
    if list_change is not None:
        key, channel, values = list_change
        SIMULATED_LIST_STATE[resource_name][channel][key] = values
        return True
    return False


def _simulated_trigger_query(resource_name: str, command: str) -> str | None:
    if resource_name not in SIMULATED_TRIGGER_STATE:
        return None
    match = re.fullmatch(r"DIG:PIN([123]):FUNC\?", command)
    if match is not None:
        return SIMULATED_DIGITAL_PINS[resource_name][int(match.group(1))]["function"]
    match = re.fullmatch(r"DIG:PIN([123]):POL\?", command)
    if match is not None:
        return SIMULATED_DIGITAL_PINS[resource_name][int(match.group(1))]["polarity"]
    if command == "DIG:TOUT:BUS?":
        return "ON" if SIMULATED_TRIGGER_STATE[resource_name]["trigger_output_bus"] else "OFF"
    trigger_setpoint = _simulated_trigger_setpoint_query(command)
    if trigger_setpoint is not None:
        kind, channel = trigger_setpoint
        key = "triggered_voltage" if kind == "voltage" else "triggered_current"
        return SIMULATED_TRIGGER_STATE[resource_name][channel][key]
    trigger_mode = _simulated_trigger_mode_query(command)
    if trigger_mode is not None:
        kind, channel = trigger_mode
        key = "voltage_mode" if kind == "voltage" else "current_mode"
        return SIMULATED_TRIGGER_STATE[resource_name][channel][key]
    match = re.fullmatch(r"TRIG:SOUR\? \(@([123])\)", command)
    if match is not None:
        return SIMULATED_TRIGGER_STATE[resource_name][int(match.group(1))]["source"]
    match = re.fullmatch(r"TRIG:DEL\? \(@([123])\)", command)
    if match is not None:
        return SIMULATED_TRIGGER_STATE[resource_name][int(match.group(1))]["delay"]
    list_query = _simulated_list_query(command)
    if list_query is not None:
        key, channel = list_query
        value = SIMULATED_LIST_STATE[resource_name][channel][key]
        if isinstance(value, list):
            return ",".join(value)
        return str(value)
    return None


def _simulated_trigger_setpoint_change(command: str) -> tuple[str, int, str] | None:
    for prefix, kind in (("VOLT:TRIG ", "voltage"), ("CURR:TRIG ", "current")):
        if command.startswith(prefix) and ",(@" in command and command.endswith(")"):
            value, channel_text = command.removeprefix(prefix).split(",(@", maxsplit=1)
            return (kind, _parse_channel_list(f"(@{channel_text}", "(@"), value)
    return None


def _simulated_trigger_setpoint_query(command: str) -> tuple[str, int] | None:
    for prefix, kind in (("VOLT:TRIG? (@", "voltage"), ("CURR:TRIG? (@", "current")):
        if command.startswith(prefix) and command.endswith(")"):
            return (kind, _parse_channel_list(command, prefix))
    return None


def _simulated_trigger_mode_change(command: str) -> tuple[str, int, str] | None:
    for prefix, kind in (("VOLT:MODE ", "voltage"), ("CURR:MODE ", "current")):
        if command.startswith(prefix) and ",(@" in command and command.endswith(")"):
            mode, channel_text = command.removeprefix(prefix).split(",(@", maxsplit=1)
            if mode not in {"FIX", "STEP", "LIST"}:
                raise VisaConnectionError(f"Unsupported simulated trigger mode command {command!r}")
            return (kind, _parse_channel_list(f"(@{channel_text}", "(@"), mode)
    return None


def _simulated_trigger_mode_query(command: str) -> tuple[str, int] | None:
    for prefix, kind in (("VOLT:MODE? (@", "voltage"), ("CURR:MODE? (@", "current")):
        if command.startswith(prefix) and command.endswith(")"):
            return (kind, _parse_channel_list(command, prefix))
    return None


def _simulated_trigger_source_change(command: str) -> tuple[int, str] | None:
    if command.startswith("TRIG:SOUR ") and ",(@" in command and command.endswith(")"):
        source, channel_text = command.removeprefix("TRIG:SOUR ").split(",(@", maxsplit=1)
        if source not in {"BUS", "IMM", "PIN1", "PIN2", "PIN3", "EXT"}:
            raise VisaConnectionError(f"Unsupported simulated trigger source command {command!r}")
        return (_parse_channel_list(f"(@{channel_text}", "(@"), source)
    return None


def _simulated_trigger_delay_change(command: str) -> tuple[int, str] | None:
    if command.startswith("TRIG:DEL ") and ",(@" in command and command.endswith(")"):
        delay, channel_text = command.removeprefix("TRIG:DEL ").split(",(@", maxsplit=1)
        float(delay)
        return (_parse_channel_list(f"(@{channel_text}", "(@"), delay)
    return None


def _simulated_init_or_abort(command: str, prefix: str) -> int | None:
    if command.startswith(f"{prefix} (@") and command.endswith(")"):
        return _parse_channel_list(command, f"{prefix} (@")
    return None


def _simulated_list_change(command: str) -> tuple[str, int, list[str] | str] | None:
    list_commands = {
        "LIST:VOLT ": "voltage",
        "LIST:CURR ": "current",
        "LIST:DWEL ": "dwell",
        "LIST:TOUT:BOST ": "tout_bost",
        "LIST:TOUT:EOST ": "tout_eost",
        "LIST:COUN ": "count",
        "LIST:STEP ": "step",
        "LIST:TERM:LAST ": "terminate_last",
    }
    for prefix, key in list_commands.items():
        if command.startswith(prefix) and ",(@" in command and command.endswith(")"):
            values, channel_text = command.removeprefix(prefix).split(",(@", maxsplit=1)
            channel = _parse_channel_list(f"(@{channel_text}", "(@")
            if key in {"count", "step", "terminate_last"}:
                return (key, channel, values)
            return (key, channel, [item.strip() for item in values.split(",") if item.strip()])
    return None


def _simulated_list_query(command: str) -> tuple[str, int] | None:
    list_queries = {
        "LIST:VOLT? (@": "voltage",
        "LIST:CURR? (@": "current",
        "LIST:DWEL? (@": "dwell",
        "LIST:TOUT:BOST? (@": "tout_bost",
        "LIST:TOUT:EOST? (@": "tout_eost",
        "LIST:COUN? (@": "count",
        "LIST:STEP? (@": "step",
        "LIST:TERM:LAST? (@": "terminate_last",
    }
    for prefix, key in list_queries.items():
        if command.startswith(prefix) and command.endswith(")"):
            return (key, _parse_channel_list(command, prefix))
    return None


def _execute_armed_triggers(resource_name: str) -> None:
    for channel in (1, 2, 3):
        if (
            SIMULATED_TRIGGER_STATE[resource_name][channel]["armed"]
            and SIMULATED_TRIGGER_STATE[resource_name][channel]["source"] == "BUS"
        ):
            _execute_trigger(resource_name, channel)


def _execute_trigger(resource_name: str, channel: int) -> None:
    trigger_state = SIMULATED_TRIGGER_STATE[resource_name][channel]
    setpoints = SIMULATED_PROGRAMMED_SETPOINTS[resource_name][channel]
    if trigger_state["voltage_mode"] == "LIST" and trigger_state["current_mode"] == "LIST":
        list_state = SIMULATED_LIST_STATE[resource_name][channel]
        if list_state["voltage"]:
            setpoints["voltage"] = list_state["voltage"][-1]
        if list_state["current"]:
            setpoints["current"] = list_state["current"][-1]
    else:
        setpoints["voltage"] = trigger_state["triggered_voltage"]
        setpoints["current"] = trigger_state["triggered_current"]
    trigger_state["armed"] = False
