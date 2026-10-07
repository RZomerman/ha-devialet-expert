"""Offline protocol and async transport tests; no amplifier commands."""

import asyncio
import importlib.util
import math
from pathlib import Path
import struct
import sys
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "custom_components" / "devialet_expert"
# Load the independent protocol/client without importing Home Assistant.
package = types.ModuleType("devialet_test")
package.__path__ = [str(PACKAGE)]
sys.modules[package.__name__] = package
for name in ("protocol", "client"):
    spec = importlib.util.spec_from_file_location(
        f"devialet_test.{name}", PACKAGE / f"{name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

from devialet_test import client, protocol


def frame(length=345, db=-37, muted=False, power=True, channel=6, names=None):
    packet = bytearray(length)
    packet[19:26] = b"TestAmp"
    for i in range(15):
        packet[52 + i * 17] = ord("0")
    for i, name in (names or {2: "CD", 6: "Apple TV", 9: "WiFi", 13: "USB"}).items():
        offset = 52 + i * 17
        packet[offset] = ord("1")
        packet[offset + 1:offset + 17] = name.encode().ljust(16, b"\0")
    packet[307] = 0x80 if power else 0
    packet[308] = (channel << 2) | (2 if muted else 0)
    packet[310] = round(db * 2 + 195)
    packet[-2:] = protocol.crc(packet[:-2]).to_bytes(2, "big")
    return bytes(packet)


class ProtocolTests(unittest.TestCase):
    def test_both_frame_sizes_and_calibration(self):
        for length in (345, 512):
            for db in (-37, -36.5, -31):
                with self.subTest(length=length, db=db):
                    status = protocol.parse_status(frame(length, db))
                    self.assertEqual(status.volume_db, db)
                    self.assertEqual(status.name, "TestAmp")
                    self.assertEqual(status.source, "Apple TV")
                    self.assertEqual(len(status.inputs), 4)

    def test_bad_and_short_frames(self):
        bad = bytearray(frame())
        bad[-1] ^= 1
        for packet in (bytes(bad), b"", bytes(312)):
            with self.assertRaises(ValueError):
                protocol.parse_status(packet)

    def test_invalid_flags_even_with_valid_crc(self):
        bad = bytearray(frame())
        bad[52] = 2
        bad[-2:] = protocol.crc(bad[:-2]).to_bytes(2, "big")
        with self.assertRaises(ValueError):
            protocol.parse_status(bytes(bad))

    def test_duplicate_source_labels(self):
        status = protocol.parse_status(frame(names={2: "Same", 6: "Same"}))
        self.assertEqual(status.inputs, ((2, "Same [2]"), (6, "Same [6]")))

    def test_ceiling_and_invalid_volume(self):
        for value in (-27.5, 0, 20, -98, math.nan, math.inf, -math.inf):
            with self.subTest(value=value), self.assertRaises(ValueError):
                protocol.command_packet("volume", value, 0)
        self.assertEqual(protocol.level_to_db(1), -28)
        self.assertEqual(protocol.level_to_db(0), -97.5)
        for level in (-0.1, 1.1, math.nan, math.inf):
            with self.assertRaises(ValueError):
                protocol.level_to_db(level)

    def test_all_slider_values_are_safe(self):
        for index in range(1001):
            value = protocol.level_to_db(index / 1000)
            self.assertLessEqual(value, -28)
            self.assertGreaterEqual(value, -97.5)
            self.assertEqual(value * 2, int(value * 2))

    def test_upstream_volume_encoding_parity(self):
        upstream = ROOT.parent / "devialet-poc" / "devimote" / "src"
        if not upstream.exists():
            self.skipTest("Upstream source not installed")
        sys.path.insert(0, str(upstream))
        from pydevialet_expert_nonpro import DeviMoteBackEnd
        backend = DeviMoteBackEnd(host="192.0.2.1")
        captured = []
        backend._send_command = lambda packet: captured.append(bytes(packet))
        for step in range(-195, -55):
            db = step / 2
            backend.set_volume(db)
            packet = protocol.command_packet("volume", db, 0)
            self.assertEqual(packet[6:10], captured[-1][6:10], db)

    def test_framing_crc_counter_wrap_and_opcodes(self):
        for sequence in (0, 255, 256, 511, 512, 65535):
            packet = protocol.command_packet("volume", -36, sequence)
            self.assertEqual(len(packet), 142)
            self.assertEqual(packet[:2], b"Dr")
            self.assertEqual(packet[3], sequence & 255)
            self.assertEqual(packet[5], (sequence >> 1) & 255)
            self.assertEqual(protocol.crc(packet[:12]), struct.unpack(">H", packet[12:14])[0])
        for kind, value, opcode in (("power", True, 1), ("mute", True, 7), ("source", 13, 5)):
            self.assertEqual(protocol.command_packet(kind, value, 0)[7], opcode)

    def test_source_encoding_and_invalid_commands(self):
        for index in range(15):
            packet = protocol.command_packet("source", index, 0)
            self.assertEqual(packet[8], (0x4000 | index << 5) >> 8)
            self.assertEqual(packet[9], ((index << 5) & 255) >> (index > 7))
        for kind, value in (("source", 15), ("source", -1), ("source", 1.5),
                            ("source", True), ("power", 1), ("other", 0)):
            with self.assertRaises(ValueError):
                protocol.command_packet(kind, value, 0)


class FakeTransport(asyncio.DatagramTransport):
    def __init__(self):
        self.sent = []
        self.closed = False

    def sendto(self, data, addr=None):
        self.sent.append((data, addr))

    def close(self):
        self.closed = True


class ClientTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.changes = []
        self.amp = client.Client("192.0.2.1", False, lambda: self.changes.append(True))
        self.transport = FakeTransport()
        self.amp.connection_made(self.transport)
        self.receive()

    async def asyncTearDown(self):
        self.amp.close()

    def receive(self, **kwargs):
        self.amp.datagram_received(frame(**kwargs), ("192.0.2.1", 45454))

    async def test_wrong_host_and_bad_crc_do_not_update(self):
        revision = self.amp.revision
        self.amp.datagram_received(frame(db=-30), ("192.0.2.2", 45454))
        self.amp.datagram_received(b"invalid", ("192.0.2.1", 45454))
        self.assertEqual(self.amp.revision, revision)
        self.assertEqual(self.amp.status.volume_db, -37)

    async def test_read_only_blocks_every_command(self):
        self.amp.read_only = True
        for kind, value in (("volume", -36), ("step", 0.5), ("mute", True),
                            ("power", False), ("source", 2)):
            with self.assertRaises(client.CommandError):
                await self.amp.command(kind, value)
        self.assertEqual(self.transport.sent, [])

    async def test_stale_blocks_commands(self):
        self.amp.received_at -= 11
        self.assertFalse(self.amp.available)
        with self.assertRaises(client.CommandError):
            await self.amp.command("mute", True)

    async def test_fresh_readback_required(self):
        task = asyncio.create_task(self.amp.command("volume", -36))
        await asyncio.sleep(0)
        self.assertFalse(task.done())
        self.assertEqual(len(self.transport.sent), 4)
        self.receive(db=-37)
        await asyncio.sleep(0)
        self.assertFalse(task.done())
        self.receive(db=-36)
        await task
        self.assertTrue(all(addr == ("192.0.2.1", 45455) for _, addr in self.transport.sent))

    async def test_unconfirmed_command_times_out(self):
        old = client.CONFIRM_SECONDS
        client.CONFIRM_SECONDS = 0.01
        try:
            with self.assertRaises(TimeoutError):
                await self.amp.command("mute", True)
            self.assertFalse(self.amp.status.muted)
        finally:
            client.CONFIRM_SECONDS = old

    async def test_repeated_steps_serialize_and_use_latest_volume(self):
        tasks = [asyncio.create_task(self.amp.command("step", 0.5)) for _ in range(3)]
        for expected in (-36.5, -36, -35.5):
            await asyncio.sleep(0)
            self.receive(db=expected)
            await asyncio.sleep(0)
        await asyncio.gather(*tasks)
        self.assertEqual(len(self.transport.sent), 12)
        for index, expected in enumerate((-36.5, -36, -35.5)):
            self.assertEqual(
                self.transport.sent[index * 4][0][8:10],
                protocol.command_packet("volume", expected, 0)[8:10],
            )

    async def test_ceiling_rejects_steps_and_power_source_safety(self):
        self.receive(db=-28)
        with self.assertRaises(client.CommandError):
            await self.amp.command("step", 0.5)
        self.receive(db=-20, power=False)
        for kind, value in (("power", True), ("source", 2), ("volume", -27)):
            with self.assertRaises(client.CommandError):
                await self.amp.command(kind, value)
        self.assertEqual(self.transport.sent, [])

    async def test_invalid_input_and_noop(self):
        with self.assertRaises(client.CommandError):
            await self.amp.command("source", 3)
        await self.amp.command("mute", False)
        self.assertEqual(self.transport.sent, [])

    async def test_network_error_and_recovery(self):
        self.amp.error_received(OSError("network failed"))
        self.assertFalse(self.amp.available)
        self.receive()
        self.assertTrue(self.amp.available)

    async def test_close_releases_transport(self):
        self.amp.close()
        self.assertTrue(self.transport.closed)
        self.assertFalse(self.amp.available)


if __name__ == "__main__":
    unittest.main()
