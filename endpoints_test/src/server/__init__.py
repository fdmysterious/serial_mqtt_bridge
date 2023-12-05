from transitions.extensions import AsyncGraphMachine
from types                  import SimpleNamespace

from loguru import logger

import asyncio
import serial
import serial_asyncio

import aiomqtt

from dataclasses import dataclass

from config.schema import (
    MqttConfig,
    SerialConfig,
)

@dataclass
class ServerConfig:
    mqtt: MqttConfig
    serial: SerialConfig


class ServerStateMachine(object):
    STATES = (
        {"name": "inactive"       },
        {"name": "lock_request"   },
        {"name": "active"         },
        {"name": "unlock_request" },
        {"name": "replace_request"},
    )

    @classmethod
    def __gen_fsm(cls, model):
        """
        Generate the state machine object
        """
        machine = AsyncGraphMachine(model=model, states=cls.STATES, initial="inactive")

        # Lock is requested from an endpoint
        machine.add_transition(trigger="lock", source="inactive", dest="lock_request", after = "action_endpoint_lock_request")

        # Lock request is allowed by server
        machine.add_transition(trigger="lock_ok", source="lock_request", dest="active", before = "action_endpoint_lock_ok")

        # Lock request is not allowed by server
        machine.add_transition(trigger="lock_fail", source="lock_request", dest="inactive", before = "action_endpoint_lock_fail")

        # Another endpoint wants to lock
        machine.add_transition(trigger="lock", source="active", dest="replace_request", before="action_endpoint_replace_request", after="action_endpoint_ask_replace")

        # Unlock requested from active endpoint
        machine.add_transition(trigger="unlock", source="active", dest="unlock_request", after = "action_check_unlock_capability")

        # Unlock is validated from server to endpoint
        machine.add_transition(trigger="unlock_yes", source="unlock_request", dest="inactive", before = "action_endpoint_unlock_yes")

        # Unlock is not validated from server to endpoint
        machine.add_transition(trigger="unlock_no", source="unlock_request", dest="active", before="action_endpoint_unlock_no")

        # Replace is accepted by active endpoint
        machine.add_transition(trigger="replace_yes", source="replace_request", dest="active", after = "action_replace_done")

        # Replace is not accepted by active endpoint
        machine.add_transition(trigger="replace_no", source="replace_request", dest="active", after = "action_replace_reject")

        # Replace is accepted after timeout from currently active endpoint
        machine.add_transition(trigger="replace_timeout", source="replace_request", dest="active", after = "action_replace_done")

        return machine

    @classmethod
    def generate_graph(cls):
        """
        Utility function to generate the FSM's graph
        """
        obj     = SimpleNamespace()
        machine = cls.__gen_fsm(obj)
        return machine.get_graph()


    # ------------------------------------------------------------- #

    def __init__(self, config: ServerConfig):
        self.config = config
        self.fsm    = self.__gen_fsm(self)

        self.client = None                     # MQTT client object
        self.topic  = config.mqtt.topic_prefix # Base topic

        self.active_endpoint  = None           # Current endpoint name
        self.replace_endpoint = None           # Endpoint replace candidate

        self.timeout_task     = None           # Current timeout task

        self.serial_reader    = None           # Asyncio reader for serial port
        self.serial_writer    = None           # Asyncio writer for serial port

        self.mqtt_opened      = asyncio.Event()
        self.serial_opened    = asyncio.Event()

        self.read_buffer      = bytearray()   # Buffer to store received data when no endpoint is active


    # --------------- Utilities

    async def do_after_timeout(self, timeout, action, *args):
        await asyncio.sleep(timeout)
        logger.info("Reached timeout")
        await action(*args)


    async def ensure_mqtt_opened(self):
        async with asyncio.timeout(0.1):
            await self.mqtt_opened.wait()

    async def ensure_serial_opened(self):
        async with asyncio.timeout(0.1):
            await self.serial_opened.wait()


    # --------------- Generic message sends functions

    async def send_endpoint_client_msg(self, endpoint, msg):
        await self.ensure_mqtt_opened()
        logger.debug(f"Sending message '{msg}' to endpoint '{endpoint}'")
        await self.client.publish(f"{self.topic}/endpoints/{endpoint}/request/client_endpoint", payload=msg.encode("ascii"))

    async def send_endpoint_client_data(self, endpoint, data):
        await self.ensure_mqtt_opened()

        logger.debug(f"Sending data '{data}' to endpoint '{endpoint}'")
        await self.client.publish(f"{self.topic}/endpoints/{endpoint}/in", payload=data)

    async def send_current_endpoint(self, endpoint):
        await self.ensure_mqtt_opened()

        logger.debug(f"Indicating current endpoint: '{endpoint}'")
        await self.client.publish(f"{self.topic}/current_endpoint", payload=endpoint.encode("ascii"))

    async def send_received_data(self, data):
        await self.ensure_mqtt_opened()

        logger.debug("Send received data to spy endpoint")
        await self.client.publish(f"{self.topic}/in", payload=data)


    # --------------- Run function

    async def run(self):
        logger.info("Starting server...")
        async with asyncio.TaskGroup() as tg:
            tg.create_task(self.mqtt_worker())
            tg.create_task(self.serial_worker())


    # --------------- MQTT Worker and associated callbacks

    async def mqtt_worker(self):
        logger.info("Starting MQTT worker task...")
        async with aiomqtt.Client(
            hostname = self.config.mqtt.host, 
            port     = self.config.mqtt.port,
            username = self.config.mqtt.username,
            password = self.config.mqtt.password,
        ) as client:
            self.client = client
            self.mqtt_opened.set()
            async with self.client.messages() as messages:
                await self.client.subscribe(f"{self.topic}/endpoints/+/request/server_endpoint")
                await self.client.subscribe(f"{self.topic}/endpoints/+/out")

                async for message in messages:
                    if message.topic.matches(f"{self.topic}/endpoints/+/request/server_endpoint"):
                        await self.process_server_req(message)
                    elif self.active_endpoint and message.topic.matches(f"{self.topic}/endpoints/{self.active_endpoint}/out"):
                        logger.info("Received data")
                        await self.serial_write(message.payload)


    async def process_server_req(self, message):
        req      = message.payload.decode("ascii")
        endpoint = message.topic.value.replace(f"{self.topic}/endpoints/","").replace("/request/server_endpoint", "")

        logger.info(f"Procesing server request '{req}' on endpoint '{endpoint}'")

        if   req == "lock"   and ((self.state == "inactive") or (self.state == "active")) and (endpoint != self.active_endpoint):
            await self.lock(endpoint)
        elif req == "unlock" and (self.state == "active") and (endpoint == self.active_endpoint):
            await self.unlock(endpoint)
        elif req == "yes" and (self.state == "replace_request") and (endpoint == self.active_endpoint):
            await self.replace_yes()
        elif req == "no"  and (self.state == "replace_request") and (endpoint == self.active_endpoint):
            await self.replace_no()


    # --------------- Serial worker and associated callbacks

    async def serial_worker(self):
        logger.info("Starting serial worker...")
        self.serial_reader, self.serial_writer = await serial_asyncio.open_serial_connection(
            url       = self.config.serial.path,
            baudrate  = self.config.serial.baudrate,
            parity    = self.config.serial.parity.to_pyserial(),
            stopbits  = self.config.serial.stop_bits.to_pyserial(),
            rtscts    = self.config.serial.hwflow,
            dsrdtr    = False,# FIXME # Add feature in config schema
            exclusive = True
        )

        self.serial_opened.set()

        while True:
            read_byte = await self.serial_reader.read(1)
            await self.serial_received_data(read_byte)


    async def serial_received_data(self):
        # Send received data to active endpoint
        if self.active_endpoint is not None:
            if self.read_buffer:
                await self.send_endpoint_client_data(self.active_endpoint, bytes(self.read_buffer))
                self.read_buffer = bytearray()
            await self.send_endpoint_client_data(self.active_endpoint, data)

        # Send to spy endpoint
        await self.send_received_data(data)


    async def serial_write(self, data):
        await self.ensure_serial_opened()
        await self.ensure_mqtt_opened()

        logger.debug(f"Writing on serial port: {data}")

        # Send to serial buffer
        self.serial_writer.write(data)

        # Send to spy endpoint
        await self.client.publish(f"{self.topic}/out", data)

        # Drain buffered data to serial port
        await self.serial_writer.drain()


    # --------------- Transitions actions

    async def action_endpoint_lock_request(self, endpoint):
        # For now, the first arrived is the first served!
        await self.lock_ok(endpoint)

    async def action_check_unlock_capability(self, endpoint):
        # For now, if the endpoint wants to unlock, it gets it
        await self.unlock_yes(self.active_endpoint)

    async def action_endpoint_replace_request(self, endpoint):
        self.replace_endpoint = endpoint # A new replace candidate is on!

    async def action_endpoint_ask_replace(self, endpoint):
        await self.send_endpoint_client_msg(self.active_endpoint, "unlock")
        self.timeout_task = asyncio.create_task(self.do_after_timeout(0.1, self.replace_timeout))

    async def action_replace_done(self):
        logger.info(f"Replace done for endpoint {self.replace_endpoint}")
        if self.timeout_task:
            self.timeout_task.cancel()
            self.timeout_task = None

        self.active_endpoint = self.replace_endpoint
        await self.send_current_endpoint(self.active_endpoint)          # Indicate new active endpoint
        await self.send_endpoint_client_msg(self.active_endpoint, "ok") # Confirm replace request to new endpoint

    async def action_replace_reject(self):
        logger.info(f"Replace replace for endpoint {self.replace_endpoint}")
        endp = self.replace_endpoint
        self.replace_endpoint = None

        if self.timeout_task:
            self.timeout_task.cancel()
            self.timeout_task = None
        await self.send_endpoint_client_msg(endp, "fail")               # Reject replace request to replace candidate


    async def action_endpoint_lock_ok(self, endpoint):
        self.active_endpoint = endpoint
        await self.send_current_endpoint(endpoint)                      # Indicate new active endpoint on topic
        await self.send_endpoint_client_msg(endpoint, "ok")             # Confirm lock request to endpoint client

    async def action_endpoint_lock_fail(self, endpoint):
        await self.send_endpoint_client_msg(endpoint, "fail")           # Indicate lock failure to endpoint client

    async def action_endpoint_unlock_yes(self, endpoint):
        self.active_endpoint = None
        await self.send_current_endpoint("")                            # Indicate new inactive endpoint on topic
        await self.send_endpoint_client_msg(endpoint, "yes")            # Confirm unlock request to endpoint client

    async def action_endpoint_unlock_no(self, endpoint):
        await self.send_endpoint_client_msg(endpoint, "no")             # Indicate unlock failure to endpoint client
