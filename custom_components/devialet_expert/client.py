"""Nonblocking, host-pinned UDP receiver and confirmed command sender."""

import asyncio
from collections.abc import Callable
import logging

from .protocol import (
    COMMAND_PORT, STATUS_PORT, Status, command_packet, parse_status,
    quantize_db,
)

_LOGGER = logging.getLogger(__name__)
STALE_SECONDS = 10.0
CONFIRM_SECONDS = 5.0


class CommandError(Exception):
    """A command could not safely execute or be confirmed."""


class Client(asyncio.DatagramProtocol):
    def __init__(self, host: str, read_only: bool, changed: Callable[[], None]) -> None:
        self.host = host
        self.read_only = read_only
        self.changed = changed
        self.status: Status | None = None
        self.transport: asyncio.DatagramTransport | None = None
        self.received_at = 0.0
        self.revision = 0
        self.sequence = 0
        self.network_error: str | None = None
        self._lock = asyncio.Lock()
        self._received = asyncio.Event()
        self._expiry: asyncio.TimerHandle | None = None
        self._last_invalid_log = float("-inf")

    @property
    def available(self) -> bool:
        return (
            self.transport is not None
            and self.network_error is None
            and self.status is not None
            and asyncio.get_running_loop().time() - self.received_at < STALE_SECONDS
        )

    async def start(self) -> None:
        await asyncio.get_running_loop().create_datagram_endpoint(
            lambda: self, local_addr=("0.0.0.0", STATUS_PORT)
        )
        try:
            await asyncio.wait_for(self._received.wait(), STALE_SECONDS)
            if not self.available:
                raise OSError(self.network_error or "No valid amplifier status")
        except (TimeoutError, OSError, asyncio.CancelledError):
            self.close()
            raise

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        if not isinstance(transport, asyncio.DatagramTransport):
            raise TypeError("Devialet requires a datagram transport")
        self.transport = transport

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        if addr[0] != self.host:
            return
        loop = asyncio.get_running_loop()
        try:
            status = parse_status(data)
        except (ValueError, UnicodeDecodeError) as err:
            if loop.time() - self._last_invalid_log >= STALE_SECONDS:
                _LOGGER.warning("Invalid Devialet status from %s: %s", self.host, err)
                self._last_invalid_log = loop.time()
            return
        was_available = self.available
        old = self.status
        self.status = status
        self.received_at = loop.time()
        self.network_error = None
        self.revision += 1
        self._received.set()
        if self._expiry:
            self._expiry.cancel()
        self._expiry = loop.call_later(STALE_SECONDS, self.changed)
        if old != status or not was_available:
            self.changed()

    def error_received(self, exc: Exception) -> None:
        self.network_error = str(exc)
        _LOGGER.error("Devialet UDP error: %s", exc)
        self._received.set()
        self.changed()

    def connection_lost(self, exc: Exception | None) -> None:
        self.transport = None
        if exc:
            self.error_received(exc)
        else:
            self.changed()

    def close(self) -> None:
        if self._expiry:
            self._expiry.cancel()
            self._expiry = None
        if self.transport:
            self.transport.close()
            self.transport = None
        self._received.set()

    async def command(self, kind: str, value: bool | int | float) -> None:
        async with self._lock:
            if self.read_only:
                raise CommandError("Controls are disabled (read-only mode)")
            status = self.status
            transport = self.transport
            if not self.available or status is None or transport is None:
                raise CommandError("No recent valid amplifier status")
            expected: bool | int | float
            if kind in ("volume", "step"):
                if isinstance(value, bool):
                    raise CommandError("Volume requires a number")
                try:
                    expected = quantize_db(
                        status.volume_db + value if kind == "step" else value
                    )
                except ValueError as err:
                    raise CommandError(str(err)) from err
                kind = "volume"
                matches = lambda s: s.volume_db == expected
            elif kind in ("power", "mute"):
                if not isinstance(value, bool):
                    raise CommandError("Power/mute require a boolean")
                expected = value
                matches = (
                    (lambda s: s.power == expected) if kind == "power"
                    else (lambda s: s.muted == expected)
                )
            elif kind == "source":
                if value not in dict(status.inputs) or isinstance(value, bool):
                    raise CommandError("Input is not advertised by the amplifier")
                expected = value
                matches = lambda s: s.channel == expected
            else:
                raise CommandError(f"Unknown command: {kind}")
            if matches(status):
                return
            revision = self.revision
            try:
                for _ in range(4):
                    transport.sendto(
                        command_packet(kind, expected, self.sequence),
                        (self.host, COMMAND_PORT),
                    )
                    self.sequence = (self.sequence + 1) % 512
            except (OSError, ValueError) as err:
                raise CommandError(f"Cannot send Devialet command: {err}") from err
            async with asyncio.timeout(CONFIRM_SECONDS):
                while True:
                    self._received.clear()
                    if not self.available:
                        raise CommandError("Amplifier disconnected during command")
                    if self.revision > revision and self.status and matches(self.status):
                        return
                    await self._received.wait()
