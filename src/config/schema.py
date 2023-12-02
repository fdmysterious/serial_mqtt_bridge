"""
===============================
Configuration schema definition
===============================

:Authors: - Florian Dupeyron <florian.dupeyron@mugcat.fr>
:Date: December 2023
"""

from dataclasses import dataclass
from typing      import Optional
from enum        import Enum


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
        if not isinstance(x["hwflow"], bool):
            raise ValueError(f"hwflow is a '{type(x['hwflow'])}', not a 'bool'")
        if not isinstance(x["path"], str):
            raise ValueError(f"path is a '{type(x['path'])}, not a 'str'")

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
        if not isinstance(x["host"], str):
            raise ValueError(f"host is a '{type(x['host'])}, not a 'str'")
        if not isinstance(x["topic_prefix"], str):
            raise ValueError(f"topic_prefix is a '{type(x['topic_prefix'])}, not a 'str'")
        if "username" in x and not isinstance(x["username"], str):
            raise ValueError(f"username is a '{type(x['username'])}, not a 'str'")
        if "password" in x and not isinstance(x["password"], str):
            raise ValueError(f"password is a '{type(x['password'])}, not a 'str'")

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
            serial = SerialConfig.from_dict(x["serial"]),
            mqtt   = MqttConfig.from_dict(x["mqtt"]),
        )
