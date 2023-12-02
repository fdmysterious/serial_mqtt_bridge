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

class SerialStopBits(Enum):
    One      = 1
    Two      = 2

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
class EndpointSerialMirrorConfig:
    name: str
    path: str

    @classmethod
    def from_dict(cls, x):
        _check_type(x, "name", str)
        _check_type(x, "path", str)

        return cls(
            name = x["name"],
            path = x["path"],
        )


@dataclass
class EndpointVirtualConfig:
    name: str

    @classmethod
    def from_dict(cls, x):
        _check_type(x, "name", str)

        return cls(
            name = x["name"],
        )

@dataclass
class EndpointConfig:
    ENDPOINT_PROVIDERS = {
        "serial-mirror":  EndpointSerialMirrorConfig,
        "virtual":        EndpointVirtualConfig, 
    }

    provider:    str
    config_data: any

    @classmethod
    def from_dict(cls, x):
        _check_type(x, "provider", str)

        if not x["provider"] in cls.ENDPOINT_PROVIDERS:
            raise ValueError(f"Unknown endpoint provider: {x['provider']}")

        return cls(
            provider    = x["provider"],
            config_data = cls.ENDPOINT_PROVIDERS[x['provider']].from_dict(x)
        )


@dataclass
class ConfigSchema:
    serial: SerialConfig
    mqtt: MqttConfig
    endpoints: Tuple[EndpointConfig]

    @classmethod
    def from_dict(cls, x):
        return cls(
            serial    = SerialConfig.from_dict(x["serial"]),
            mqtt      = MqttConfig.from_dict(x["mqtt"]),
            endpoints = tuple(map(EndpointConfig.from_dict, x.get("endpoints", []))),
        )
