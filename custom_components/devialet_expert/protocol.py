"""Experimental Expert non-Pro UDP protocol based on devimote's wire format."""

from dataclasses import dataclass
import binascii
import math
import struct

STATUS_PORT = 45454
COMMAND_PORT = 45455
MIN_DB = -97.5
MAX_DB = -28.0
STEP_DB = 0.5


@dataclass(frozen=True)
class Status:
    name: str
    power: bool
    muted: bool
    channel: int
    volume_db: float
    inputs: tuple[tuple[int, str], ...]

    @property
    def source(self) -> str | None:
        return dict(self.inputs).get(self.channel)


def crc(data: bytes | bytearray) -> int:
    return binascii.crc_hqx(data, 0xFFFF)


def parse_status(data: bytes) -> Status:
    if len(data) < 313:
        raise ValueError("Status frame is too short")
    if crc(data[:-2]) != int.from_bytes(data[-2:], "big"):
        raise ValueError("Status CRC mismatch")

    def text(start: int, end: int) -> str:
        return data[start:end].split(b"\0", 1)[0].decode("utf-8").strip()

    inputs = []
    for index in range(15):
        offset = 52 + index * 17
        if data[offset] not in (ord("0"), ord("1")):
            raise ValueError("Invalid input enabled flag")
        if data[offset] == ord("1"):
            name = text(offset + 1, offset + 17)
            inputs.append((index, name or f"Input {index}"))
    # Duplicate labels must still be selectable independently in HA.
    labels = [name for _, name in inputs]
    inputs = [
        (index, f"{name} [{index}]" if labels.count(name) > 1 else name)
        for index, name in inputs
    ]
    return Status(
        name=text(19, 50) or "Devialet Expert",
        power=bool(data[307] & 0x80),
        muted=bool(data[308] & 0x02),
        channel=(data[308] & 0x3C) >> 2,
        volume_db=(data[310] - 195) / 2,
        inputs=tuple(inputs),
    )


def quantize_db(value: float) -> float:
    if not math.isfinite(value) or not MIN_DB <= value <= MAX_DB:
        raise ValueError(f"Volume must be between {MIN_DB} and {MAX_DB} dB")
    return min(MAX_DB, max(MIN_DB, round(value / STEP_DB) * STEP_DB))


def level_to_db(level: float) -> float:
    if not math.isfinite(level) or not 0 <= level <= 1:
        raise ValueError("Volume level must be finite and between 0 and 1")
    return quantize_db(MIN_DB + level * (MAX_DB - MIN_DB))


def db_to_level(value: float) -> float:
    return min(1.0, max(0.0, (value - MIN_DB) / (MAX_DB - MIN_DB)))


def volume_word(value: float) -> int:
    """Reproduce devimote's unusual encoding, not an assumed IEEE half float."""
    magnitude = abs(quantize_db(value))
    word = 0x3F00
    while magnitude > 0.5:
        word += 256 >> math.ceil(1 + math.log2(magnitude))
        magnitude -= 0.5
    return word | 0x8000


def command_packet(kind: str, value: bool | int | float, sequence: int) -> bytes:
    packet = bytearray(142)
    packet[:2] = b"Dr"
    packet[3] = sequence & 0xFF
    packet[5] = (sequence >> 1) & 0xFF
    if kind in ("power", "mute"):
        if not isinstance(value, bool):
            raise ValueError("Power/mute require a boolean")
        packet[6] = int(value)
        packet[7] = 0x01 if kind == "power" else 0x07
    elif kind == "volume":
        if isinstance(value, bool):
            raise ValueError("Volume requires a number")
        packet[7] = 0x04
        struct.pack_into(">H", packet, 8, volume_word(value))
    elif kind == "source":
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value < 15:
            raise ValueError("Source index must be between 0 and 14")
        word = 0x4000 | (value << 5)
        packet[7] = 0x05
        packet[8] = word >> 8
        packet[9] = (word & 0xFF) >> (1 if value > 7 else 0)
    else:
        raise ValueError(f"Unknown command: {kind}")
    struct.pack_into(">H", packet, 12, crc(packet[:12]))
    return bytes(packet)
