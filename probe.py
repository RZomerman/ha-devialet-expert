"""Listen for the configured amplifier; never transmit."""

import argparse
import asyncio
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent / "custom_components" / "devialet_expert"))
from protocol import STATUS_PORT, parse_status


async def listen(host: str, seconds: float) -> None:
    import socket

    loop = asyncio.get_running_loop()
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setblocking(False)
        sock.bind(("0.0.0.0", STATUS_PORT))
        async with asyncio.timeout(seconds):
            while True:
                data, addr = await loop.sock_recvfrom(sock, 2048)
                if addr[0] != host:
                    continue
                try:
                    status = parse_status(data)
                except (ValueError, UnicodeDecodeError) as err:
                    print(f"Rejected packet from {addr[0]}: {err}", file=sys.stderr)
                    continue
                print(
                    f"{addr[0]}: {status.name}, power={status.power}, "
                    f"mute={status.muted}, input={status.source}, "
                    f"volume={status.volume_db} dB, bytes={len(data)}"
                )
                print(f"Inputs: {dict(status.inputs)}")
                return


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", required=True)
    parser.add_argument("--seconds", type=float, default=15)
    args = parser.parse_args()
    try:
        asyncio.run(listen(args.host, args.seconds))
    except TimeoutError:
        parser.exit(1, "No readable Devialet status: listen timed out\n")
    except OSError as err:
        parser.exit(1, f"No readable Devialet status: {err}\n")
