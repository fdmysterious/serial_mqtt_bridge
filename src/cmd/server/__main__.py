from server import ServerStateMachine, ServerConfig

import asyncio
import toml

from argparse      import ArgumentParser, ArgumentTypeError
from loguru        import logger
from pathlib       import Path

from config.schema import ConfigSchema

import toml

def validate_path(path):
    path = Path(path)
    if not path.exists():
        raise ArgumentTypeError(f"The specified config file '{config_path}' does not exist.")
    return path


async def main():
    logger.info("Hello world!")

    # Arguments
    parser = ArgumentParser(description = "Serial bridge over MQTT")
    parser.add_argument("--config", type=validate_path, required=True, help="Path to toml config file.")

    args = parser.parse_args()

    # Load config file
    logger.info("Load config file")
    config_data = dict()
    with open(args.config, "r") as fhandle:
        config_data = toml.load(fhandle)

    config_file = ConfigSchema.from_dict(config_data)

    # Start server
    server = ServerStateMachine(
        config = ServerConfig(
            mqtt   = config_file.mqtt,
            serial = config_file.serial,
        )
    )

    await server.run()


if __name__ == "__main__":
    asyncio.run(main())
