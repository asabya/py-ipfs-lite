# tests/bitswap/test_network.py
import pytest
import trio
from unittest.mock import AsyncMock, MagicMock
from multiformats import CID, multihash

from ipfs_lite.block import Block
from ipfs_lite.blockstore.memory import MemoryBlockstore
from ipfs_lite.bitswap.protocol import BitswapProtocol
from ipfs_lite.bitswap.network import BitswapNetwork, encode_message, decode_message, _cid_key
from ipfs_lite.bitswap.wantlist import Wantlist, WantType
from ipfs_lite.bitswap.message import Message, BlockPresence, BlockPresenceType


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


def test_broadcast_want_two_phase():
    """broadcast_want sends want-have first, then want-block to HAVE peers."""

    async def _run():
        block = Block.from_data(b"two phase", codec="raw")
        bs = MemoryBlockstore()
        protocol = BitswapProtocol(bs)

        host = MagicMock()
        host.new_stream = AsyncMock(return_value=MockStream(b""))

        network = BitswapNetwork(host, protocol)
        cid_str = _cid_key(block.cid)

        # Simulate HAVE arrival after want-have is sent, then block arrival after want-block
        async def inject_have():
            await trio.sleep(0.05)
            peer_id = "QmFakePeer"
            network._have_peers.setdefault(cid_str, []).append(peer_id)
            ev = network._have_events.get(cid_str)
            if ev is not None:
                ev.set()
            # Inject block after want-block would be sent
            await trio.sleep(0.05)
            bs.put(block)
            bev = network._block_events.get(cid_str)
            if bev is not None:
                bev.set()

        peer_info = MagicMock()
        peer_info.peer_id = "QmFakePeer"

        async with trio.open_nursery() as nursery:
            nursery.start_soon(inject_have)
            result = await network.broadcast_want([peer_info], block.cid)

        assert result is not None
        assert result.payload[0].data == b"two phase"

    trio.run(_run)


async def test_handle_stream_have_fires_have_event():
    """handle_stream fires _have_events when HAVE presence arrives for tracked CID."""
    bs = MemoryBlockstore()
    protocol = BitswapProtocol(bs)
    network = BitswapNetwork(None, protocol)

    block = Block.from_data(b"have test", codec="raw")
    cid_str = _cid_key(block.cid)

    # Register as an active two-phase want
    have_event = trio.Event()
    network._have_events[cid_str] = have_event
    network._have_peers[cid_str] = []

    # Build inbound stream carrying a HAVE presence
    presence_msg = Message(
        block_presences=[BlockPresence(cid=block.cid, type=BlockPresenceType.Have)]
    )
    stream = MockStream(_frame(encode_message(presence_msg)))

    await network.handle_stream(stream)

    assert have_event.is_set()


def test_wait_for_block_uses_block_events():
    """wait_for_block resolves via _block_events when block arrives."""

    async def _run():
        bs = MemoryBlockstore()
        block = Block.from_data(b"wait block", codec="raw")
        cid_str = _cid_key(block.cid)
        protocol = BitswapProtocol(bs)
        network = BitswapNetwork(None, protocol)

        # Pre-register via add_wants so block_event exists
        network.add_wants([block.cid])

        async def deliver():
            await trio.sleep(0.05)
            bs.put(block)
            ev = network._block_events.get(cid_str)
            if ev is not None:
                ev.set()

        async with trio.open_nursery() as nursery:
            nursery.start_soon(deliver)
            result = await network.wait_for_block(block.cid, timeout=2.0)

        assert result is not None
        assert result.data == b"wait block"

    trio.run(_run)


def test_run_sender_sends_want_have():
    """_run_sender broadcasts want-have (not want-block) to connected peers."""

    async def _run():
        bs = MemoryBlockstore()
        block = Block.from_data(b"passive", codec="raw")
        protocol = BitswapProtocol(bs)

        written_msgs = []

        async def fake_stream_write(data):
            written_msgs.append(data)

        fake_stream = MagicMock()
        fake_stream.write = AsyncMock(side_effect=fake_stream_write)
        fake_stream.close = AsyncMock()

        host = MagicMock()
        host.new_stream = AsyncMock(return_value=fake_stream)
        host.get_connected_peers = MagicMock(return_value=["QmPeerA"])

        network = BitswapNetwork(host, protocol)

        async def stop_after_send(nursery):
            await trio.sleep(0.1)
            nursery.cancel_scope.cancel()

        network.add_wants([block.cid])

        async with trio.open_nursery() as nursery:
            nursery.start_soon(network._run_sender)
            nursery.start_soon(stop_after_send, nursery)

        assert len(written_msgs) == 1
        # Decode the written message
        data = bytes(written_msgs[0])
        _, offset = _decode_varint(data, 0)
        msg = decode_message(data[offset:])
        assert msg.wantlist is not None
        assert msg.wantlist.entries[0].want_type == WantType.Have

    trio.run(_run)


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
