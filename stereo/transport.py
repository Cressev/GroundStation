"""Bounded TCP framing shared verbatim by the relay and the ground station."""

import json
import socket
import struct
import time

MAX_PACKET = 16 * 1024 * 1024
MAX_META = 4096
STEREO_FRAME, CALIBRATION, MESSAGE, LEGACY_JPEG = 0xFD, 0xFC, 0xFE, 0xFF


def encode_packet(kind, body):
    """Prefix a bounded message with its network-order length and type."""
    if not 0 < len(body) + 1 <= MAX_PACKET:
        raise ValueError('Invalid packet size')
    return struct.pack('!IB', len(body) + 1, kind) + body


def encode_blob(metadata, data):
    """Bind metadata to the exact binary frame or calibration it describes."""
    header = json.dumps(metadata, separators=(',', ':'), allow_nan=False).encode('utf-8')
    if not 0 < len(header) <= MAX_META:
        raise ValueError('Invalid metadata size')
    return struct.pack('!H', len(header)) + header + data


def decode_blob(body):
    """Validate the metadata boundary before decoding an atomic blob."""
    if len(body) < 3:
        raise ValueError('Truncated blob')
    size = struct.unpack('!H', body[:2])[0]
    if not 0 < size <= MAX_META or 2 + size >= len(body):
        raise ValueError('Invalid metadata boundary')
    metadata = json.loads(body[2:2 + size].decode('utf-8'))
    if not isinstance(metadata, dict):
        raise ValueError('Metadata must be an object')
    return metadata, body[2 + size:]


def receive_exact(connection, size, cancelled, progress_timeout=15.0):
    """Keep partial bytes across timeouts; stop dead peers with a partial packet."""
    if not 0 < size <= MAX_PACKET:
        raise ValueError('Invalid receive size')
    data = bytearray()
    last_progress = time.monotonic()
    while len(data) < size and not cancelled():
        try:
            part = connection.recv(size - len(data))
        except socket.timeout:
            if data and time.monotonic() - last_progress > progress_timeout:
                raise TimeoutError('Stalled partial packet')
            continue
        if not part:
            return None
        data.extend(part)
        last_progress = time.monotonic()
    return bytes(data) if len(data) == size else None
