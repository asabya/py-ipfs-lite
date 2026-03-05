# tests/bitswap/test_network.py
import pytest
from multiformats import CID, multihash

from ipfs_lite.block import Block
from ipfs_lite.blockstore.memory import MemoryBlockstore
from ipfs_lite.bitswap.protocol import BitswapProtocol
from ipfs_lite.bitswap.network import BitswapNetwork, encode_message, decode_message
from ipfs_lite.bitswap.wantlist import Wantlist, WantType
from ipfs_lite.bitswap.message import Message, BlockPresenceType


class MockStream:
    """In-memory stream for testing."""

    def __init__(self, data: bytes = b""):
        self._buf = bytearray(data)
        self.written = bytearray()
        self.closed = False

    async def read(self, n: int) -> bytes:
        chunk = bytes(self._buf[:n])
        self._buf = self._buf[n:]
        return chunk

    async def write(self, data: bytes) -> None:
        self.written.extend(data)

    async def close(self) -> None:
        self.closed = True


def _encode_varint(n: int) -> bytes:
    buf = []
    while n > 0x7F:
        buf.append((n & 0x7F) | 0x80)
        n >>= 7
    buf.append(n & 0x7F)
    return bytes(buf)


def _decode_varint(data: bytes, pos: int) -> tuple[int, int]:
    n, shift = 0, 0
    while True:
        b = data[pos]; pos += 1
        n |= (b & 0x7F) << shift
        if not (b & 0x80):
            break
        shift += 7
    return n, pos


def _frame(data: bytes) -> bytes:
    return _encode_varint(len(data)) + data


def test_network_has_two_phase_state():
    """BitswapNetwork exposes new per-CID tracking dicts."""
    from ipfs_lite.blockstore.memory import MemoryBlockstore
    from ipfs_lite.bitswap.protocol import BitswapProtocol
    bs = MemoryBlockstore()
    protocol = BitswapProtocol(bs)
    network = BitswapNetwork(None, protocol)
    assert hasattr(network, '_have_events')
    assert hasattr(network, '_have_peers')
    assert hasattr(network, '_block_events')
    assert hasattr(network, '_passive_cids')
    assert not hasattr(network, '_pending_wants')
    assert not hasattr(network, 'send_want')


def test_encode_decode_roundtrip():
    """Encode a Message to protobuf bytes and decode it back."""
    block = Block.from_data(b"round trip", codec="raw")
    msg = Message(payload=[block])

    encoded = encode_message(msg)
    decoded = decode_message(encoded)

    assert len(decoded.payload) == 1
    assert decoded.payload[0].data == b"round trip"


def test_encode_decode_wantlist():
    """Encode a wantlist message and decode it."""
    block = Block.from_data(b"wanted", codec="raw")
    wl = Wantlist()
    wl.add_entry(block.cid, want_type=WantType.Block, send_dont_have=True)
    msg = Message(wantlist=wl)

    encoded = encode_message(msg)
    decoded = decode_message(encoded)

    assert decoded.wantlist is not None
    assert len(decoded.wantlist.entries) == 1
    assert decoded.wantlist.entries[0].send_dont_have is True


async def test_handle_stream_returns_block():
    """handle_stream reads want, writes block response."""
    blockstore = MemoryBlockstore()
    block = Block.from_data(b"streamed block", codec="raw")
    blockstore.put(block)

    protocol = BitswapProtocol(blockstore)
    network = BitswapNetwork(None, protocol)  # host not needed for this test

    wl = Wantlist()
    wl.add_entry(block.cid, want_type=WantType.Block)
    msg = Message(wantlist=wl)
    encoded = encode_message(msg)

    stream = MockStream(_frame(encoded))
    await network.handle_stream(stream)

    assert stream.closed is True
    # Parse written response (varint-length-prefixed)
    resp_len, offset = _decode_varint(bytes(stream.written), 0)
    resp_bytes = bytes(stream.written[offset:offset + resp_len])
    response = decode_message(resp_bytes)
    assert len(response.payload) == 1
    assert response.payload[0].data == b"streamed block"
