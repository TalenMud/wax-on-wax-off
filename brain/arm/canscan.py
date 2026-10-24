"""Raw SocketCAN scan for RobStride motors. Read-only: sends only type-0 (get device ID).

    python -m brain.arm.canscan can0
"""

import socket
import struct
import sys
import time

EFF = 0x80000000


def recv_all(s: socket.socket, seconds: float) -> list[tuple[int, bytes]]:
    frames, end = [], time.time() + seconds
    s.settimeout(0.05)
    while time.time() < end:
        try:
            raw = s.recv(16)
        except socket.timeout:
            continue
        cid, dlc = struct.unpack("=IB", raw[:5])
        frames.append((cid, raw[8 : 8 + dlc]))
    return frames


def fmt(cid: int, data: bytes) -> str:
    if cid & EFF:
        c = cid & 0x1FFFFFFF
        return f"EXT type={c >> 24:2d} hi={(c >> 8) & 0xFFFF:#06x} lo={c & 0xFF:#04x} data={data.hex()}"
    return f"STD id={cid & 0x7FF:#05x} data={data.hex()}"


def main() -> None:
    ch = sys.argv[1]
    host = int(sys.argv[2], 0) if len(sys.argv) > 2 else 0xFD
    s = socket.socket(socket.AF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
    s.setsockopt(socket.SOL_CAN_RAW, socket.CAN_RAW_LOOPBACK, 0)
    s.bind((ch,))

    passive = recv_all(s, 2.0)
    print(f"[{ch}] passive 2s: {len(passive)} frames")
    for f in passive[:10]:
        print("  ", fmt(*f))

    replies = []
    for mid in range(1, 128):
        cid = EFF | (0 << 24) | (host << 8) | mid
        s.send(struct.pack("=IB3x8s", cid, 8, bytes(8)))
        replies += recv_all(s, 0.01)
    replies += recv_all(s, 0.3)
    print(f"[{ch}] after pinging ids 1..127 from host {host:#x}: {len(replies)} frames")
    for f in replies[:30]:
        print("  ", fmt(*f))


if __name__ == "__main__":
    main()
