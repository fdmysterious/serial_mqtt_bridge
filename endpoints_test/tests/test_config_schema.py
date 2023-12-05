"""
=======================
Tests for config schema
=======================

:Authors: - Florian Dupeyron <florian.dupeyron@mugcat.fr>
:Date: December 2023
"""

from textwrap import dedent
import toml
import pytest


# ------------------------- Tests for serial config

def test_serial_config():
    from config   import schema

    config_section = dedent("""
        baudrate  = 115200
        parity    = "none"
        stop_bits = 1
        hwflow    = false
        path      = "/dev/serial/by-id/my_serial_port"
    """)

    config_dict   = toml.loads(config_section)
    serial_config = schema.SerialConfig.from_dict(config_dict)

    assert serial_config.baudrate  == 115200,                             "Invalid baudrate"
    assert serial_config.parity    == schema.SerialParity.NoParity,       "Invalid parity"
    assert serial_config.stop_bits == schema.SerialStopBits.One,          "Invalid stop_bits"
    assert serial_config.hwflow    == False,                              "Invalid hwflow"
    assert serial_config.path      == "/dev/serial/by-id/my_serial_port", "Invalid path"


def test_serial_config_invalid_baudrate():
    from config import schema

    config_section = dedent("""
        baudrate  = "super"
        parity    = "even"
        stop_bits = 1
        hwflow    = false
        path      = "/dev/serial/by-id/my_serial_port"
    """)

    config_dict   = toml.loads(config_section)

    with pytest.raises(ValueError):
        serial_config = schema.SerialConfig.from_dict(config_dict)


def test_serial_config_invalid_parity():
    from config import schema

    config_section = dedent("""
        baudrate  = 115200
        parity    = "abracadabra"
        stop_bits = 1
        hwflow    = false
        path      = "/dev/serial/by-id/my_serial_port"
    """)

    config_dict   = toml.loads(config_section)

    with pytest.raises(ValueError):
        serial_config = schema.SerialConfig.from_dict(config_dict)


def test_serial_config_invalid_stopbits():
    from config import schema

    config_section = dedent("""
        baudrate  = 115200
        parity    = "odd"
        stop_bits = 3
        hwflow    = false
        path      = "/dev/serial/by-id/my_serial_port"
    """)

    config_dict   = toml.loads(config_section)

    with pytest.raises(ValueError):
        serial_config = schema.SerialConfig.from_dict(config_dict)


def test_serial_config_invalid_hwflow():
    from config import schema

    config_section = dedent("""
        baudrate  = 115200
        parity    = "none"
        stop_bits = 1
        hwflow    = 2938
        path      = "/dev/serial/by-id/my_serial_port"
    """)

    config_dict   = toml.loads(config_section)

    with pytest.raises(ValueError):
        serial_config = schema.SerialConfig.from_dict(config_dict)


def test_serial_config_invalid_path():
    from config import schema

    config_section = dedent("""
        baudrate  = 115200
        parity    = "none"
        stop_bits = 1
        hwflow    = false
        path      = 2938
    """)

    config_dict   = toml.loads(config_section)

    with pytest.raises(ValueError):
        serial_config = schema.SerialConfig.from_dict(config_dict)


# ------------------------- Tests for mqtt config

def test_mqtt_config():
    from config import schema

    config_section = dedent("""
        host         = "localhost"
        port         = 1883
        topic_prefix = "itf/serial"
        username     = "idefix"
        password     = "1234"
    """)

    config_dict = toml.loads(config_section)

    mqtt_config = schema.MqttConfig.from_dict(config_dict)

    assert mqtt_config.host         == "localhost" , "Invalid host"
    assert mqtt_config.port         == 1883        , "Invalid port"
    assert mqtt_config.topic_prefix == "itf/serial", "Invalid topic_prefix"
    assert mqtt_config.username     == "idefix"    , "Invalid username"
    assert mqtt_config.password     == "1234"      , "Invalid password"


def test_mqtt_config_no_user_password():
    from config import schema

    config_section = dedent("""
        host         = "localhost"
        port         = 1883
        topic_prefix = "itf/serial"
    """)

    config_dict = toml.loads(config_section)

    mqtt_config = schema.MqttConfig.from_dict(config_dict)

    assert mqtt_config.host         == "localhost" , "Invalid host"
    assert mqtt_config.port         == 1883        , "Invalid port"
    assert mqtt_config.topic_prefix == "itf/serial", "Invalid topic_prefix"
    assert mqtt_config.username     == None        , "Invalid username"
    assert mqtt_config.password     == None        , "Invalid password"


def test_mqtt_config_no_password():
    from config import schema

    config_section = dedent("""
        host         = "localhost"
        port         = 1883
        topic_prefix = "itf/serial"
        username     = "idefix"
    """)

    config_dict = toml.loads(config_section)

    mqtt_config = schema.MqttConfig.from_dict(config_dict)

    assert mqtt_config.host         == "localhost" , "Invalid host"
    assert mqtt_config.port         == 1883        , "Invalid port"
    assert mqtt_config.topic_prefix == "itf/serial", "Invalid topic_prefix"
    assert mqtt_config.username     == "idefix"    , "Invalid username"
    assert mqtt_config.password     == None        , "Invalid password"


def test_mqtt_config_invalid_host():
    from config import schema

    config_section = dedent("""
        host         = 23848
        port         = 1883
        topic_prefix = "itf/serial"
        username     = "idefix"
        password     = "1234"
    """)

    config_dict = toml.loads(config_section)

    with pytest.raises(ValueError):
        mqtt_config = schema.MqttConfig.from_dict(config_dict)


def test_mqtt_config_invalid_port():
    from config import schema

    config_section = dedent("""
        host         = "localhost"
        port         = "oopsie"
        topic_prefix = "itf/serial"
        username     = "idefix"
        password     = "1234"
    """)

    config_dict = toml.loads(config_section)

    with pytest.raises(ValueError):
        mqtt_config = schema.MqttConfig.from_dict(config_dict)


def test_mqtt_config_invalid_topic_prefix():
    from config import schema

    config_section = dedent("""
        host         = "localhost"
        port         = 1883
        topic_prefix = 829383
        username     = "idefix"
        password     = "1234"
    """)

    config_dict = toml.loads(config_section)

    with pytest.raises(ValueError):
        mqtt_config = schema.MqttConfig.from_dict(config_dict)


def test_mqtt_config_invalid_username():
    from config import schema

    config_section = dedent("""
        host         = "localhost"
        port         = 1883
        topic_prefix = "itf/serial"
        username     = 20398
        password     = "1234"
    """)

    config_dict = toml.loads(config_section)

    with pytest.raises(ValueError):
        mqtt_config = schema.MqttConfig.from_dict(config_dict)


def test_mqtt_config_invalid_password():
    from config import schema

    config_section = dedent("""
        host         = "localhost"
        port         = 1883
        topic_prefix = "itf/serial"
        username     = "idefix"
        password     = 293838
    """)

    config_dict = toml.loads(config_section)

    with pytest.raises(ValueError):
        mqtt_config = schema.MqttConfig.from_dict(config_dict)


# ------------------------- Tests for global config

def test_config():
    from config import schema

    config_section = dedent("""
        [serial]
        path         = "/dev/serial/by-id/my_serial_port"
        baudrate     = 115200
        parity       = "none"
        stop_bits    = 1
        hwflow       = false

        [mqtt]
        host         = "localhost"
        port         = 1883
        topic_prefix = "itf/serial"
    """)

    config_dict = toml.loads(config_section)
    config_file = schema.ConfigSchema.from_dict(config_dict)

    assert config_file.serial.baudrate       == 115200                                        , "Invalid serial baudrate"
    assert config_file.serial.path           == "/dev/serial/by-id/my_serial_port"            , "Invalid serial path"
    assert config_file.serial.parity         == schema.SerialParity.NoParity                  , "Invalid serial parity"
    assert config_file.serial.stop_bits      == schema.SerialStopBits.One                     , "Invalid serial stop_bits"
    assert config_file.serial.hwflow         == False                                         , "Invalid serial hwflow"

    assert config_file.mqtt.host             == "localhost"                                   , "Invalid mqtt host"
    assert config_file.mqtt.port             == 1883                                          , "Invalid mqtt port"
    assert config_file.mqtt.topic_prefix     == "itf/serial"                                  , "Invalid mqtt topic_prefix"
