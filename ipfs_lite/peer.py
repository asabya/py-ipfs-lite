import logging
from typing import Optional, Any

from ipfs_lite.blockstore.interface import Blockstore
from ipfs_lite.bitswap.protocol import BitswapProtocol
from ipfs_lite.dag.service import DAGService


logger = logging.getLogger(__name__)


class IPFSLitePeer:
    """Main IPFS-Lite peer class integrating all components."""

    def __init__(
        self,
        host: Any,
        blockstore: Blockstore,
        bitswap: Optional[BitswapProtocol] = None,
    ):
        self.host = host
        self.blockstore = blockstore
        self.dag = DAGService(blockstore)
        self.bitswap = bitswap

        self._id = host.get_id()

    @property
    def peer_id(self) -> str:
        return str(self._id)

    @property
    def addrs(self):
        return self.host.get_addrs()

    def attach_bitswap(self) -> None:
        """Register bitswap protocol handler with libp2p host."""
        if self.bitswap is None:
            self.bitswap = BitswapProtocol(self.blockstore)

        self.host.set_stream_handler(
            self.bitswap.protocol_id(),
            self.bitswap.handle_message,
        )
        logger.info(f"Bitswap protocol handler registered: {self.bitswap.protocol_id()}")
