# ipfs_lite/peer.py
import logging
from typing import Any, Optional

from ipfs_lite.blockstore.interface import Blockstore
from ipfs_lite.block_service import BlockService
from ipfs_lite.bitswap.protocol import BitswapProtocol
from ipfs_lite.bitswap.network import BitswapNetwork
from ipfs_lite.exchange.bitswap import BitswapExchange
from ipfs_lite.dag.service import DAGService

logger = logging.getLogger(__name__)


class IPFSLitePeer:
    """Main IPFS-Lite peer — wires blockstore, exchange, dag, and libp2p host."""

    def __init__(self, host: Any, blockstore: Blockstore):
        self.host = host
        self.blockstore = blockstore

        protocol = BitswapProtocol(blockstore)
        self.network = BitswapNetwork(host, protocol)
        self.exchange = BitswapExchange(self.network)
        self.block_service = BlockService(blockstore, self.exchange)
        self.dag = DAGService(self.block_service)

    @property
    def peer_id(self) -> str:
        return str(self.host.get_id())

    async def start(self) -> None:
        """Register Bitswap protocol handler with the libp2p host."""
        self.host.set_stream_handler(
            BitswapNetwork.PROTOCOL_ID,
            self.network.handle_stream,
        )
        logger.info(f"IPFSLitePeer started: {self.peer_id}")

    async def connect(self, peer_info: Any) -> None:
        """Dial a remote peer."""
        await self.host.connect(peer_info)
