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
from ipfs_lite.bitswap.message import BlockPresenceType
from ipfs_lite.bitswap.wantlist import WantType


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

                await peer_a.start()
                await peer_b.start()

                # A stores a block
                block = Block.from_data(b"hello libp2p", codec="raw")
                peer_a.dag.put(block)

                # B connects to A
                peer_a_info = PeerInfo(host_a.get_id(), host_a.get_addrs())
                await peer_b.connect(peer_a_info)

                # B fetches block from A via dag.get
                retrieved = await peer_b.dag.get(block.cid, peers=[peer_a_info])

                assert retrieved is not None
                assert retrieved.data == b"hello libp2p"

    trio.run(_run)


def test_have_response():
    """Peer B checks Have presence, then fetches the actual block."""

    async def _run():
        host_a = _make_host(b"c" * 32)
        host_b = _make_host(b"d" * 32)

        async with host_a.run(listen_addrs=[LISTEN_ADDR]):
            async with host_b.run(listen_addrs=[LISTEN_ADDR]):
                peer_a = IPFSLitePeer(host_a, MemoryBlockstore())
                peer_b = IPFSLitePeer(host_b, MemoryBlockstore())

                await peer_a.start()
                await peer_b.start()

                block = Block.from_data(b"check then fetch", codec="raw")
                peer_a.dag.put(block)

                peer_a_info = PeerInfo(host_a.get_id(), host_a.get_addrs())
                await peer_b.connect(peer_a_info)

                # Step 1: Have check
                have_response = await peer_b.network.send_want(
                    peer_a_info,
                    block.cid,
                    want_type=WantType.Have,
                    send_dont_have=True,
                )
                assert have_response is not None
                assert len(have_response.block_presences) == 1
                assert have_response.block_presences[0].type == BlockPresenceType.Have

                # Step 2: Fetch actual block
                block_response = await peer_b.network.send_want(
                    peer_a_info,
                    block.cid,
                    want_type=WantType.Block,
                )
                assert block_response is not None
                assert len(block_response.payload) == 1
                assert block_response.payload[0].data == b"check then fetch"

    trio.run(_run)


def test_dont_have_response():
    """Peer A sends DontHave when it doesn't have the block."""

    async def _run():
        host_a = _make_host(b"e" * 32)
        host_b = _make_host(b"f" * 32)

        async with host_a.run(listen_addrs=[LISTEN_ADDR]):
            async with host_b.run(listen_addrs=[LISTEN_ADDR]):
                peer_a = IPFSLitePeer(host_a, MemoryBlockstore())
                peer_b = IPFSLitePeer(host_b, MemoryBlockstore())

                await peer_a.start()
                await peer_b.start()

                missing_cid = Block.from_data(b"not on A", codec="raw").cid

                peer_a_info = PeerInfo(host_a.get_id(), host_a.get_addrs())
                await peer_b.connect(peer_a_info)

                response = await peer_b.network.send_want(
                    peer_a_info,
                    missing_cid,
                    want_type=WantType.Have,
                    send_dont_have=True,
                )
                assert response is not None
                assert len(response.block_presences) == 1
                assert response.block_presences[0].type == BlockPresenceType.DontHave

    trio.run(_run)
