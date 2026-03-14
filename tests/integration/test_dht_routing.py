# tests/integration/test_dht_routing.py
"""
Integration test: DHT-based content discovery between three peers.

Peer A stores a block and provides it via DHT.
Peer C (not directly connected to A) discovers A through DHT and fetches the block.
"""
import trio
from libp2p import new_host
from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.peer.peerinfo import PeerInfo
from libp2p.kad_dht.kad_dht import KadDHT, DHTMode
from multiaddr import Multiaddr

from ipfs_lite import IPFSLitePeer, MemoryBlockstore, Block


LISTEN_ADDR = Multiaddr("/ip4/127.0.0.1/tcp/0")


def _make_host(seed: bytes):
    key_pair = create_new_key_pair(seed)
    return new_host(key_pair=key_pair)


def test_dht_content_discovery():
    """Peer C discovers and fetches a block from Peer A via DHT."""

    async def _run():
        host_a = _make_host(b"i" * 32)
        host_b = _make_host(b"j" * 32)
        host_c = _make_host(b"k" * 32)

        async with host_a.run(listen_addrs=[LISTEN_ADDR]):
            async with host_b.run(listen_addrs=[LISTEN_ADDR]):
                async with host_c.run(listen_addrs=[LISTEN_ADDR]):
                    # Create DHT nodes
                    dht_a = KadDHT(host_a, DHTMode.SERVER)
                    dht_b = KadDHT(host_b, DHTMode.SERVER)
                    dht_c = KadDHT(host_c, DHTMode.SERVER)

                    peer_a = IPFSLitePeer(host_a, MemoryBlockstore(), dht=dht_a)
                    peer_b = IPFSLitePeer(host_b, MemoryBlockstore(), dht=dht_b)
                    peer_c = IPFSLitePeer(host_c, MemoryBlockstore(), dht=dht_c)

                    async with trio.open_nursery() as nursery:
                        # start() now also starts dht.run() in the nursery
                        await peer_a.start(nursery)
                        await peer_b.start(nursery)
                        await peer_c.start(nursery)

                        # Connect: A<->B, B<->C (A and C not directly connected)
                        peer_a_info = PeerInfo(host_a.get_id(), host_a.get_addrs())
                        peer_b_info = PeerInfo(host_b.get_id(), host_b.get_addrs())

                        await peer_b.connect(peer_a_info)
                        await peer_c.connect(peer_b_info)

                        # Add peers to DHT routing tables
                        await dht_b.add_peer(host_a.get_id())
                        await dht_a.add_peer(host_b.get_id())
                        await dht_c.add_peer(host_b.get_id())
                        await dht_b.add_peer(host_c.get_id())

                        # A stores and provides a block via add_block (DHT provide + bitswap notify)
                        block = Block.from_data(b"dht discovery test", codec="raw")
                        await peer_a.add_block(block)

                        # Allow DHT records to propagate
                        await trio.sleep(0.5)

                        # C fetches the block -- should discover A via DHT
                        retrieved = await peer_c.dag.get(block.cid)

                        assert retrieved is not None, "Block should be found via DHT"
                        assert retrieved.data == b"dht discovery test"
                        nursery.cancel_scope.cancel()

    trio.run(_run)
