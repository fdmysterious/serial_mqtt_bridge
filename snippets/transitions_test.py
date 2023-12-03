from transitions.extensions        import AsyncGraphMachine
from transitions.extensions.states import Timeout, add_state_features
from types                         import SimpleNamespace

import aiomqtt
import serial
import serial_asyncio
import paho.mqtt as mqtt

import logging
from loguru import logger

import asyncio

class UsedFSM(AsyncGraphMachine):
    pass

class ServerStateMachine(object):
    STATES = (
        {"name": "inactive"        },
        {"name": "lock_request"    },
        {"name": "active"          },
        {"name": "unlock_request"  },
        {"name": "replace_request" },
    )

    @classmethod
    def __gen_fsm(cls, model):
        machine = UsedFSM(model=model, states=cls.STATES, initial="inactive")

        machine.add_transition(trigger="lock"            , source = "inactive"       , dest="lock_request"   , after  = "action_endpoint_lock_request"                                          )
        machine.add_transition(trigger="lock_ok"         , source = "lock_request"   , dest="active"         , before = "action_endpoint_lock_ok"                                               )
        machine.add_transition(trigger="lock_fail"       , source = "lock_request"   , dest="inactive"       , before = "action_endpoint_lock_fail"                                             )
        machine.add_transition(trigger="lock"            , source = "active"         , dest="replace_request", before = "action_endpoint_replace_request", after = "action_endpoint_ask_replace")
        machine.add_transition(trigger="unlock"          , source = "active"         , dest="unlock_request" , after  = "action_check_unlock_capability"                                        )
        machine.add_transition(trigger="unlock_yes"      , source = "unlock_request" , dest="inactive"       , before = "action_endpoint_unlock_yes"                                            )
        machine.add_transition(trigger="unlock_no"       , source = "unlock_request" , dest="active"         , before = "action_endpoint_unlock_no"                                             )
        machine.add_transition(trigger="replace_yes"     , source = "replace_request", dest="active"         , after  = "action_replace_done"                                                   )
        machine.add_transition(trigger="replace_no"      , source = "replace_request", dest="active"         , after  = "action_replace_reject"                                                 )
        machine.add_transition(trigger="replace_timeout" , source = "replace_request", dest="active"         , after  = "action_replace_done"                                                   )

        return machine

    @classmethod
    def generate_graph(cls):
        logger.info("Generating graph")
        obj     = SimpleNamespace()
        machine = cls.__gen_fsm(obj)
        return machine.get_graph()

    def __init__(self, client, topic, serial_path):
        self.machine             = self.__gen_fsm(self)
        self.client              = client # MQTT client object
        self.topic               = topic  # Base topic 

        self.active_endpoint     = None   # Current active endpoint
        self.replace_endpoint    = None   # Replace candidate

        self.timeout_task        = None   # Current timeout task

        self.serial_path         = serial_path
        self.serial_reader       = None   # Asyncio reader
        self.serial_writer       = None   # Asyncio writer for serial

        self.serial_opened       = asyncio.Event()
        self.read_buffer         = bytearray()


    # ------------------- Worker and request processing

    async def mqtt_worker(self):
        logger.info("Starting server worker task...")
        async with self.client.messages() as messages:
            await self.client.subscribe(f"{self.topic}/endpoints/+/request/server_endpoint")
            async for message in messages:
                if message.topic.matches(f"{self.topic}/endpoints/+/request/server_endpoint"):
                    await self.process_server_req(message)

    async def process_server_req(self, message):
        req      = message.payload.decode("ascii")
        endpoint = message.topic.value.replace(f"{self.topic}/endpoints/", "").replace("/request/server_endpoint", "")

        logger.info(f"Processing server request '{req}' on endpoint '{endpoint}'")

        if req == "lock":
            if (self.state == "inactive") or (self.state == "active"):
                await self.lock(endpoint)
        elif req == "unlock":
            if (self.state == "active"):
                await self.unlock(endpoint)
        elif req == "yes":
            if (self.state == "replace_request") and (endpoint == self.active_endpoint):
                await self.replace_yes()
        elif req == "no":
            if (self.state == "replace_request") and (endpoint == self.replace_endpoint):
                await self.replace_no()


    # ------------------- Worker and request processing

    async def serial_received_data(self, data):
        # Send received data to active endpoint
        if self.active_endpoint is not None:
            if self.read_buffer:
                await self.send_data_to_endpoint(self.active_endpoint, bytes(self.read_buffer))
                self.read_buffer = bytearray()
            await self.send_data_to_endpoint(self.active_endpoint, data)

        # Send to spy endpoint
        await self.send_received_data(data)


    async def serial_worker(self):
        logger.info("Starting serial worker...")
        self.serial_reader, self.serial_writer = await serial_asyncio.open_serial_connection(
            url      = self.serial_path,
            baudrate = 115200,
            parity   = serial.PARITY_NONE,
            stopbits = serial.STOPBITS_ONE,
            timeout  = 0.1
        )

        self.serial_opened.set()

        while True:
            read_byte  = await self.serial_reader.read(1)
            await self.serial_received_data(read_byte)

    async def serial_write(self, data):
        logger.info(f"Writing on serial port: {data}")
        async with asyncio.timeout(0.1):
            await self.serial_opened.wait()
        self.serial_writer.write(data)

        # Send to spy endpoint
        await self.client.publish(f"{self.topic}/out", data)

        # Drain buffered data to serial port
        await self.serial_writer.drain()


    # ------------------- Generic message send

    async def send_to_endpoint_client(self, endpoint, msg):
        logger.debug(f"Sending message '{msg}' to endpoint '{endpoint}'")
        await self.client.publish(f"{self.topic}/endpoints/{endpoint}/request/client_endpoint", payload=msg.encode("ascii"))

    async def send_current_endpoint(self, endpoint):
        logger.debug(f"Set current endpoint to '{endpoint}'")
        await self.client.publish(f"{self.topic}/current_endpoint", payload=endpoint.encode("ascii"))

    async def send_received_data(self, data):
        logger.debug(f"Send received data to spy endpoint")
        await self.client.publish(f"{self.topic}/in", payload=data)

    async def send_data_to_endpoint(self, endpoint, data):
        logger.debug(f"Sending data '{data}' to endpoint '{endpoint}'")
        await self.client.publish(f"{self.topic}/endpoints/{endpoint}/in", payload=data)


    # ------------------- Utilities

    async def do_after_timeout(self, timeout, action, *args):
        await asyncio.sleep(timeout)
        logger.info("timeout!")
        await action(*args)


    # ------------------- Transitions actions

    async def action_endpoint_lock_request(self, endpoint):
        await self.lock_ok(endpoint)

    async def action_endpoint_lock_ok(self, endpoint):
        self.active_endpoint = endpoint
        await self.send_current_endpoint(endpoint)
        await self.send_to_endpoint_client(endpoint, "ok")

    async def action_endpoint_lock_fail(self, endpoint):
        await self.send_to_endpoint_client(endpoint, "fail")

    async def action_check_unlock_capability(self, endpoint):
        await self.unlock_yes(self.active_endpoint)

    async def action_endpoint_unlock_yes(self, endpoint):
        self.active_endpoint = None
        await self.send_current_endpoint("")
        await self.send_to_endpoint_client(endpoint, "yes")

    async def action_endpoint_unlock_no(self, endpoint):
        await self.send_to_endpoint_client(endpoint, "no")

    async def action_endpoint_replace_request(self, endpoint):
        self.replace_endpoint = endpoint

    async def action_endpoint_ask_replace(self, endpoint):
        await self.send_to_endpoint_client(self.active_endpoint, "unlock")
        self.timeout_task = asyncio.create_task(self.do_after_timeout(0.1, self.replace_timeout))

    async def action_check_replace_capability(self, endpoint):
        await self.replace_yes(self.endpoint)

    async def action_replace_done(self):
        logger.info(f"Replace done for endpoint {self.replace_endpoint}")
        if self.timeout_task:
            self.timeout_task.cancel()
            self.timeout_task = None

        self.active_endpoint  = self.replace_endpoint
        self.replace_endpoint = None
        await self.send_current_endpoint(self.active_endpoint)
        await self.send_to_endpoint_client(self.active_endpoint, "ok")

    async def action_replace_reject(self):
        logger.info(f"Reject replace for endpoint {self.replace_endpoint}")
        endp = self.replace_endpoint
        self.replace_endpoint = None

        if self.timeout_task:
            self.timeout_task.cancel()
            self.timeout_task = None

        await self.send_to_endpoint_client(endp, "fail")


# ------------------------------------------------------------------- 


class ClientStateMachine(object):
    STATES = (
        {"name": "inactive"        },
        {"name": "lock_request"    },
        {"name": "active"          },
        {"name": "unlock_request"  },
        {"name": "unlock_requested"},
    )

    @classmethod
    def __gen_fsm(cls, model):
        machine = UsedFSM(model=model, states=cls.STATES, initial="inactive")
        machine.add_transition(trigger="lock"            , source="inactive"        , dest = "lock_request"    , after  = "action_lock")
        machine.add_transition(trigger="lock_ok"         , source="lock_request"    , dest = "active"          , before = "action_timeout_stop")
        machine.add_transition(trigger="lock_fail"       , source="lock_request"    , dest = "inactive"        , before = "action_timeout_stop")
        machine.add_transition(trigger="lock_timeout"    , source="lock_request"    , dest = "inactive")
        machine.add_transition(trigger="unlock_request"  , source="active"          , dest = "unlock_request"  , after = "action_unlock")
        machine.add_transition(trigger="unlock_yes"      , source="unlock_request"  , dest = "inactive")
        machine.add_transition(trigger="unlock_no"       , source="unlock_request"  , dest = "active") 
        machine.add_transition(trigger="unlock_requested", source="active"          , dest = "unlock_requested", after  = "action_check_unlock_capability")
        machine.add_transition(trigger="unlock_cannot"   , source="unlock_requested", dest = "active"          , before = "action_unlock_cannot")
        machine.add_transition(trigger="unlock_can"      , source="unlock_requested", dest = "inactive"        , before = "action_unlock_can")

        return machine

    @classmethod
    def generate_graph(cls):
        logger.info("Generating graph")
        obj = SimpleNamespace()
        machine = cls.__gen_fsm(obj)
        return machine.get_graph()

    def __init__(self, client, base_topic, name):
        self.machine         = self.__gen_fsm(self)
        self.client          = client
        self.base_topic      = base_topic
        self.name            = name
        self.log             = logger.bind(endpoint=name)

        self.timeout_task    = None

        self.test_timeout    = False


    # ------------------- Utilities

    async def do_after_timeout(self, timeout, action, *args):
        await asyncio.sleep(timeout)
        logger.info("timeout on client!")
        await action(*args)


    # ------------------- Generic message send

    async def send_message(self, msg):
        self.log.debug(f"Send '{msg}' message to server")
        await self.client.publish(f"{self.base_topic}/{self.name}/request/server_endpoint", payload=msg.encode("ascii"))


    # ------------------- Transitions actions

    async def action_timeout_stop(self):
        if self.timeout_task is not None:
            self.timeout_task.cancel()
            self.timeout_task = None

    async def action_lock(self):
        await self.send_message("lock")
        self.timeout_task = asyncio.create_task(self.do_after_timeout(0.2, self.lock_timeout))

    async def action_unlock(self):
        await self.send_message("unlock")

    async def action_check_unlock_capability(self):
        if not self.test_timeout:
            await self.unlock_can()

    async def action_unlock_can(self):
        await self.send_message("yes")

    async def action_unlock_cannot(self):
        await self.send_message("no")


    # ------------------- Worker and request processing

    async def mqtt_worker(self):
        self.log.info("Starting client worker task...")
        async with self.client.messages() as messages:
            await self.client.subscribe(f"{self.base_topic}/{self.name}/request/client_endpoint")
            async for message in messages:
                if message.topic.matches(f"{self.base_topic}/{self.name}/request/client_endpoint"):
                    await self.process_client_req(message)

    async def process_client_req(self, message):
        payload = message.payload.decode("ascii")

        self.log.info(f"Processing client request '{payload}' on endpoint '{self.name}'")

        if payload == "unlock":
            await self.unlock_requested()
        elif payload == "ok":
            await self.lock_ok()
        elif payload == "fail":
            await self.lock_fail()
        elif payload == "yes":
            await self.unlock_yes()
        elif payload == "no":
            await self.unlock_no()


# ------------------------------------------------------------------- 

async def client_task():
    async with aiomqtt.Client("localhost") as client:
        client_fsm = ClientStateMachine(client, "interfaces/serial/endpoints", "serial")

        async with asyncio.TaskGroup() as tg:
            tg.create_task(client_fsm.mqtt_worker())

            await asyncio.sleep(1)
            await client_fsm.lock()
            await asyncio.sleep(1)
            await client_fsm.unlock_request()
            await asyncio.sleep(1)
            await client_fsm.lock()

            # Client is replaced 
            await asyncio.sleep(2)

            await client_fsm.lock()

async def client2_task():
    async with aiomqtt.Client("localhost") as client:
        client_fsm = ClientStateMachine(client, "interfaces/serial/endpoints", "serial2")
        client_fsm.test_timeout = True

        async with asyncio.TaskGroup() as tg:
            tg.create_task(client_fsm.mqtt_worker())

            await asyncio.sleep(4)
            await client_fsm.lock()
            await asyncio.sleep(1)



async def server_task():
    logger.info("Starting server task...")
    async with aiomqtt.Client("localhost") as client:
        server_fsm = ServerStateMachine(client, "interfaces/serial", "/dev/serial/by-id/usb-FTDI_UART_Adapter-if00-port0")

        async with asyncio.TaskGroup() as tg:
            tg.create_task(server_fsm.mqtt_worker())
            tg.create_task(server_fsm.serial_worker())

            await asyncio.sleep(10)

            await server_fsm.serial_write("Hello world".encode("ascii"));

async def main():
    logging.basicConfig(level=logging.DEBUG)
    logging.getLogger("transitions").setLevel(logging.DEBUG)

    async with asyncio.TaskGroup() as tg:
        tg.create_task(server_task())
        tg.create_task(client_task())
        tg.create_task(client2_task())

if __name__ == "__main__":
    logger.info("Hello world!")

    ServerStateMachine.generate_graph().draw("server_fsm.png", prog="dot")
    ClientStateMachine.generate_graph().draw("client_fsm.png", prog="dot")


    asyncio.run(main())




