import argparse
from dataclasses import dataclass, asdict, field
from enum        import Enum, IntEnum

from functools   import partial

import time
import serial

import json

import asyncio
import aiomqtt
import serial_asyncio

from   pathlib import Path

from pprint import pprint

from loguru import logger

class SerialParity(Enum):
    NoParity = "none"
    Odd      = "odd"
    Even     = "even"

    def to_pyserial(self):
        if   self == self.NoParity: return serial.PARITY_NONE
        elif self == self.Odd:      return serial.PARITY_ODD
        elif self == self.Even:     return serial.PARITY_EVEN

class SerialStopBits(IntEnum):
    One = 1
    Two = 2

    def to_pyserial(self):
        if   self == self.One: return serial.STOPBITS_ONE
        elif self == self.Two: return serial.STOPBITS_TWO

###

@dataclass
class SerialSettings:
    baudrate: int
    stopbits: SerialStopBits
    parity: SerialParity
    rtscts: bool
    dsrdtr: bool

    def __post_init__(self):
        self.baudrate = int(self.baudrate)
        self.stopbits = SerialStopBits(self.stopbits)
        self.parity   = SerialParity(self.parity)
        self.rtscts   = bool(self.rtscts)
        self.dsrdtr   = bool(self.dsrdtr)

    def to_dict(self):
        return {
            "baudrate": self.baudrate,
            "parity"  : self.parity.value,
            "stopbits": self.stopbits.value,
            "rtscts"  : self.rtscts,
            "dsrdtr"  : self.dsrdtr
        }

    @classmethod
    def from_dict(cls, dd):
        return cls(
            baudrate = int(dd["baudrate"]),
            parity   = SerialParity(dd["parity"]),
            stopbits = SerialStopBits(dd["stopbits"]),
            rtscts   = bool(dd["rtscts"]),
            dsrdtr   = bool(dd["dsrdtr"]),
        )

@dataclass
class SerialBridge:
    mqtt_client: aiomqtt.Client
    serial_reader: asyncio.StreamReader
    serial_writer: asyncio.StreamWriter

    serial_settings: SerialSettings

    path: str
    topic: str

    request_settings_change: asyncio.Queue  = field(default_factory=partial(asyncio.Queue,1))
    request_settings_changed: asyncio.Event = field(default_factory=asyncio.Event)

    # -----------------------

    async def heartbeat_worker(self):
        while True:
            await asyncio.sleep(1)
            await self.mqtt_client.publish(f"{self.topic}/heartbeat", payload=str(time.time()).encode("ascii"), qos=0, retain=False)

    async def serial_worker(ctx):
        logger.info("Starting serial worker...")
        rx_buffer = bytearray()

        while True:
            if not ctx.request_settings_change.empty():
                new_settings = await ctx.request_settings_change.get()
                logger.info("Applying new serial settings")

                # Note: object could also be accessed from serial_writer
                ctx.serial_writer.transport.serial.baudrate = new_settings.baudrate
                ctx.serial_writer.transport.serial.parity   = new_settings.parity.to_pyserial()
                ctx.serial_writer.transport.serial.stopbits = new_settings.stopbits.to_pyserial()
                ctx.serial_writer.transport.serial.rtscts   = new_settings.rtscts
                ctx.serial_writer.transport.serial.dsrdtr   = new_settings.dsrdtr

                ctx.serial_settings = new_settings
                logger.info("👌 Settings applied")

                ctx.request_settings_changed.set()


            try:
                async with asyncio.timeout(0.001):
                    read_byte  = await ctx.serial_reader.read(1)
                    rx_buffer += read_byte
            except TimeoutError:
                # Dump read data on endpoint
                if rx_buffer:
                    await ctx.mqtt_client.publish(f"{ctx.topic}/in", payload=bytes(rx_buffer), qos=2)
                    rx_buffer = bytearray()

    async def mqtt_put_serial_settings(ctx):
        logger.info("Publish serial settings")
        await ctx.mqtt_client.publish(
            f"{ctx.topic}/settings",
            json.dumps(ctx.serial_settings.to_dict()).encode("ascii"),
            qos=0,
            retain=True
        )

    @logger.catch
    async def apply_settings(ctx, received_payload):
        logger.info("Requesting serial settings change")
        serial_settings = SerialSettings(**json.loads(received_payload.decode("ascii")))
        logger.debug(serial_settings)

        ctx.request_settings_changed.clear()
        await ctx.request_settings_change.put(serial_settings)
        await ctx.request_settings_changed.wait()


    async def mqtt_worker(ctx):
        logger.info("Starting MQTT worker...")
        async with ctx.mqtt_client.messages() as messages:
            await ctx.mqtt_client.subscribe(f"{ctx.topic}/out",      qos=2)

            # Publish initial serial settings
            await ctx.mqtt_put_serial_settings()

            await ctx.mqtt_client.subscribe(f"{ctx.topic}/settings", qos=0)

            async for message in messages:
                if message.topic.matches(f"{ctx.topic}/out"):
                    logger.info("Send data")
                    ctx.serial_writer.write(message.payload)
                    await ctx.serial_writer.drain()

                elif message.topic.matches(f"{ctx.topic}/settings"):
                    logger.info("Received new serial settings")
                    try:
                        await ctx.apply_settings(message.payload)
                    except:
                        pass # Ignore errors


async def main(args):
    serial_reader, serial_writer = await serial_asyncio.open_serial_connection(
        url           = args.path,
        baudrate      = args.baudrate,
        stopbits      = args.stopbits.to_pyserial(),
        parity        = args.parity.to_pyserial(),
        rtscts        = args.rtscts,
        dsrdtr        = args.dsrdtr,
    )

    async with aiomqtt.Client(
        hostname = args.broker_url,
        port     = args.broker_port,
        username = args.broker_user,
        password = args.broker_passwd
    ) as mqtt_client:
        ctx=SerialBridge(
            mqtt_client   = mqtt_client,
            serial_reader = serial_reader,
            serial_writer = serial_writer,
            topic         = args.topic,
            path          = args.path,
            serial_settings = SerialSettings(
                baudrate = args.baudrate,
                parity   = args.parity,
                stopbits = args.stopbits,
                rtscts   = args.rtscts,
                dsrdtr   = args.dsrdtr
            )
        )

        async with asyncio.TaskGroup() as tg:
            tg.create_task(ctx.serial_worker())
            tg.create_task(ctx.mqtt_worker())
            tg.create_task(ctx.heartbeat_worker())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Simple serial bridge over MQTT" )

    # Serial port options
    serial_opt = parser.add_argument_group("Serial options")
    serial_opt.add_argument("--path"       , type=str,                              help="Path to serial port device"                         , required=True                         )
    serial_opt.add_argument("--baudrate"   , type=int ,                             help="Baudrate for serial port"                           , required=True                         )
    serial_opt.add_argument("--parity"     , type=SerialParity,                     help="Serial parity"                                      , required=True                         )
    serial_opt.add_argument("--stopbits"   , type=lambda x: SerialStopBits(int(x)), help="Serial stop bits"                                   , required=True                         )
    serial_opt.add_argument("--rtscts"     , type=bool,                             help="Enable RTS/CTS HW flow"  , default=False            , required=False, const=True, nargs="?" )
    serial_opt.add_argument("--dsrdtr"     , type=bool,                             help="Enable DSR/DTR HW flow"  , default=False            , required=False, const=True, nargs="?" )


    # MQTT options
    mqtt_opt = parser.add_argument_group("MQTT options")
    mqtt_opt.add_argument("--broker-url"   , type=str,                              help="Path to MQTT broker host"                           , required=True                         )
    mqtt_opt.add_argument("--broker-port"  , type=int,                              help="Host port on broker"     , default=1883             , required=False                        )
    mqtt_opt.add_argument("--broker-user"  , type=str,                              help="Username for MQTT broker", default=None             , required=False                        )
    mqtt_opt.add_argument("--broker-passwd", type=str,                              help="Password for MQTT broker", default=None             , required=False                        )
    mqtt_opt.add_argument("--topic"        , type=str,                              help="Base topic for bridge"                              , required=True                         )

    ###

    args = parser.parse_args()

    ###

    logger.info("Hello world!")
    logger.info("Parameters:")
    logger.info( "-----------------------------------------------------------")
    logger.info(f"👉 Serial path:      {args.path}"                           )
    logger.info(f"👉 Serial baudrate:  {args.baudrate}"                       )
    logger.info(f"👉 Serial parity:    {args.parity.value}"                   )
    logger.info(f"👉 Serial stop bits: {args.stopbits.value}"                 )
    logger.info(f"👉 Serial RTS/CTS:   {args.rtscts}"                         )
    logger.info(f"👉 Serial DSR/DTR:   {args.dsrdtr}"                         )
    logger.info(f"👉 Broker URL:       {args.broker_url!s}"                   )
    logger.info(f"👉 Broker port:      {args.broker_port!s}"                  )
    logger.info(f"👉 Broker username:  {args.broker_user or '<anonymous>'}"   )
    logger.info(f"👉 Broker password:  {args.broker_user or '<no password>'}" )
    logger.info( "-----------------------------------------------------------")

    asyncio.run(main(args))