# tests/integration/test_two_peers.py
"""
Integration tests for two-peer block exchange over real TCP loopback streams.

py-libp2p is built on trio, so tests use trio.run() directly rather than
pytest-asyncio, which would use asyncio and conflict with libp2p's trio internals.
"""
import trio
from libp2p import new_host
from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.peer.peerinfo import PeerInfo
from multiaddr import Multiaddr

from ipfs_lite import IPFSLitePeer, MemoryBlockstore, Block


LISTEN_ADDR = Multiaddr("/ip4/127.0.0.1/tcp/0")


def _make_host(seed: bytes):
    """Create a libp2p host from a deterministic seed."""
    key_pair = create_new_key_pair(seed)
    return new_host(key_pair=key_pair)


def test_block_exchange():
    """Peer B fetches a block from Peer A over a real TCP loopback stream."""

    async def _run():
        host_a = _make_host(b"a" * 32)
        host_b = _make_host(b"b" * 32)

        async with host_a.run(listen_addrs=[LISTEN_ADDR]):
            async with host_b.run(listen_addrs=[LISTEN_ADDR]):
                peer_a = IPFSLitePeer(host_a, MemoryBlockstore())
                peer_b = IPFSLitePeer(host_b, MemoryBlockstore())

                async with trio.open_nursery() as nursery:
                    await peer_a.start(nursery)
                    await peer_b.start(nursery)

                    # A stores a block
                    block = Block.from_data(b"hello libp2p", codec="raw")
                    peer_a.dag.put(block)

                    # B connects to A
                    peer_a_info = PeerInfo(host_a.get_id(), host_a.get_addrs())
                    await peer_b.connect(peer_a_info)

                    # B fetches block from A via dag.get (two-phase want-have→want-block)
                    retrieved = await peer_b.dag.get(block.cid, peers=[peer_a_info])

                    assert retrieved is not None
                    assert retrieved.data == b"hello libp2p"
                    nursery.cancel_scope.cancel()

    trio.run(_run)


def test_two_phase_block_exchange():
    """Peer B fetches a block from Peer A using the two-phase want-have→want-block flow."""

    async def _run():
        host_a = _make_host(b"c" * 32)
        host_b = _make_host(b"d" * 32)

        async with host_a.run(listen_addrs=[LISTEN_ADDR]):
            async with host_b.run(listen_addrs=[LISTEN_ADDR]):
                peer_a = IPFSLitePeer(host_a, MemoryBlockstore())
                peer_b = IPFSLitePeer(host_b, MemoryBlockstore())

                async with trio.open_nursery() as nursery:
                    await peer_a.start(nursery)
                    await peer_b.start(nursery)

                    block = Block.from_data(b"two phase exchange", codec="raw")
                    peer_a.dag.put(block)

                    peer_a_info = PeerInfo(host_a.get_id(), host_a.get_addrs())
                    await peer_b.connect(peer_a_info)

                    # broadcast_want does want-have first, then want-block to HAVE peers
                    retrieved = await peer_b.dag.get(block.cid, peers=[peer_a_info])

                    assert retrieved is not None
                    assert retrieved.data == b"two phase exchange"
                    nursery.cancel_scope.cancel()

    trio.run(_run)


def test_dont_have_returns_none():
    """broadcast_want returns None when no peer has the block."""

    async def _run():
        host_a = _make_host(b"e" * 32)
        host_b = _make_host(b"f" * 32)

        async with host_a.run(listen_addrs=[LISTEN_ADDR]):
            async with host_b.run(listen_addrs=[LISTEN_ADDR]):
                peer_a = IPFSLitePeer(host_a, MemoryBlockstore())
                peer_b = IPFSLitePeer(host_b, MemoryBlockstore())

                async with trio.open_nursery() as nursery:
                    await peer_a.start(nursery)
                    await peer_b.start(nursery)

                    missing_cid = Block.from_data(b"not on A", codec="raw").cid
                    peer_a_info = PeerInfo(host_a.get_id(), host_a.get_addrs())
                    await peer_b.connect(peer_a_info)

                    # Peer A will respond DONT_HAVE → no HAVE peers → returns None
                    result = await peer_b.network.broadcast_want([peer_a_info], missing_cid)
                    assert result is None
                    nursery.cancel_scope.cancel()

    trio.run(_run)


def test_block_push_after_want():
    """Peer A wants a block, Peer B adds it later — A receives it via push."""

    async def _run():
        host_a = _make_host(b"g" * 32)
        host_b = _make_host(b"h" * 32)

        async with host_a.run(listen_addrs=[LISTEN_ADDR]):
            async with host_b.run(listen_addrs=[LISTEN_ADDR]):
                peer_a = IPFSLitePeer(host_a, MemoryBlockstore())
                peer_b = IPFSLitePeer(host_b, MemoryBlockstore())

                async with trio.open_nursery() as nursery:
                    await peer_a.start(nursery)
                    await peer_b.start(nursery)

                    # Connect A → B
                    peer_b_info = PeerInfo(host_b.get_id(), host_b.get_addrs())
                    await peer_a.connect(peer_b_info)

                    # Create block (not stored on B yet)
                    block = Block.from_data(b"pushed later", codec="raw")

                    # A sends want-have to B (B won't have it yet → DONT_HAVE)
                    # Then register passive want so A listens for push
                    peer_a.dag.want([block.cid])

                    # Small delay to let want propagate
                    await trio.sleep(0.2)

                    # B stores the block — notify_new_blocks should push to A
                    peer_b.dag.put(block)

                    # A waits for block via push
                    retrieved = await peer_a.dag.wait_for_block(block.cid)

                    assert retrieved is not None
                    assert retrieved.data == b"pushed later"
                    nursery.cancel_scope.cancel()

    trio.run(_run)
