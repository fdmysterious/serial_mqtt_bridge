"""
===============================
Configuration schema definition
===============================

:Authors: - Florian Dupeyron <florian.dupeyron@mugcat.fr>
:Date: December 2023
"""

from dataclasses import dataclass
from typing      import Optional, List, Tuple
from enum        import Enum


import serial


def _check_type(x, field_name, tt):
    """
    Utility function to check dictionary type with a standard
    error message.
    """
    if not isinstance(x[field_name], tt):
        raise ValueError(f"'{field_name}' is a '{type(x[field_name])}', not a '{tt.__name__}'")

def _check_opt_type(x, field_name, tt):
    """
    Like _check_type, but for optional values
    """

    if field_name in x:
        _check_type(x, field_name, tt)


############################################################

class SerialParity(Enum):
    NoParity = "none"
    Odd      = "odd"
    Even     = "even"

    def to_pyserial(self):
        if self == self.NoParity:
            return serial.PARITY_NONE
        elif self == self.Odd:
            return serial.PARITY_ODD
        elif self == self.Even:
            return serial.PARITY_EVEN

class SerialStopBits(Enum):
    One      = 1
    Two      = 2

    def to_pyserial(self):
        if self == self.One:
            return serial.STOPBITS_ONE
        elif self == self.Two:
            return serial.STOPBITS_TWO

@dataclass
class SerialConfig:
    baudrate: int
    parity: SerialParity
    stop_bits: SerialStopBits
    hwflow: bool
    path: str

    @classmethod
    def from_dict(cls, x):
        _check_type(x, "hwflow", bool)
        _check_type(x, "path"  , str )

        return cls(
            baudrate  = int(x["baudrate"]),
            parity    = SerialParity(x["parity"]),
            stop_bits = SerialStopBits(x["stop_bits"]),
            hwflow    = bool(x["hwflow"]),
            path      = str(x["path"]),
        )

@dataclass
class MqttConfig:
    host: str
    port: int
    topic_prefix: str
    username: Optional[str]
    password: Optional[str]

    @classmethod
    def from_dict(cls, x):
        _check_type    (x, "host"        , str)
        _check_type    (x, "topic_prefix", str)
        _check_opt_type(x, "username"    , str)
        _check_opt_type(x, "password"    , str)

        return cls(
            host         = str(x["host"]),
            port         = int(x["port"]),
            topic_prefix = str(x["topic_prefix"]),
            username     = x.get("username"),
            password     = x.get("password"),
        )

@dataclass
class ConfigSchema:
    serial: SerialConfig
    mqtt: MqttConfig

    @classmethod
    def from_dict(cls, x):
        return cls(
            serial    = SerialConfig.from_dict(x["serial"]),
            mqtt      = MqttConfig.from_dict(x["mqtt"]),
        )
