# ipfs_lite/peer.py
import logging
from typing import Any, List, Optional

from ipfs_lite.block import Block
from ipfs_lite.blockstore.interface import Blockstore
from ipfs_lite.block_service import BlockService
from ipfs_lite.bitswap.protocol import BitswapProtocol, BITSWAP_PROTOCOL_IDS
from ipfs_lite.bitswap.network import BitswapNetwork
from ipfs_lite.exchange.bitswap import BitswapExchange
from ipfs_lite.dag.service import DAGService

logger = logging.getLogger(__name__)


class IPFSLitePeer:
    """Main IPFS-Lite peer — wires blockstore, exchange, dag, and libp2p host."""

    def __init__(self, host: Any, blockstore: Blockstore, dht: Any = None):
        self.host = host
        self.blockstore = blockstore
        self.dht = dht

        protocol = BitswapProtocol(blockstore)
        self.network = BitswapNetwork(host, protocol)
        self.exchange = BitswapExchange(self.network, dht=dht)
        self.block_service = BlockService(blockstore, self.exchange)
        self.dag = DAGService(self.block_service)

    @property
    def peer_id(self) -> str:
        return str(self.host.get_id())

    async def start(self, nursery=None) -> None:
        """Register Bitswap protocol handler, start background loops, and optionally start DHT."""
        for proto in BITSWAP_PROTOCOL_IDS:
            self.host.set_stream_handler(proto, self.network.handle_stream)
        if nursery is not None:
            nursery.start_soon(self.network._run_sender)
            nursery.start_soon(self.network._run_outbound_sender)
            if self.dht is not None:
                nursery.start_soon(self.dht.run)
        logger.info(f"IPFSLitePeer started: {self.peer_id}")

    async def connect(self, peer_info: Any) -> None:
        """Dial a remote peer."""
        await self.host.connect(peer_info)

    async def add_block(self, block: Block) -> None:
        """Store a block locally, notify bitswap peers, and provide via DHT."""
        self.dag.put(block)
        if self.dht is not None:
            try:
                await self.dht.provide(str(block.cid))
            except Exception as e:
                logger.warning(f"DHT provide failed for {block.cid}: {e}")

    async def bootstrap(self, peers: List[Any]) -> None:
        """Connect to bootstrap peers and add them to DHT routing table."""
        for peer_info in peers:
            try:
                await self.host.connect(peer_info)
                if self.dht is not None:
                    await self.dht.add_peer(peer_info.peer_id)
            except Exception as e:
                logger.warning(f"Failed to bootstrap to {peer_info.peer_id}: {e}")
