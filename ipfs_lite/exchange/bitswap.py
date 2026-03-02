# ipfs_lite/exchange/bitswap.py
import logging
from typing import List, Optional

from multiformats import CID

from ipfs_lite.block import Block
from ipfs_lite.bitswap.network import BitswapNetwork
from ipfs_lite.bitswap.wantlist import WantType
from ipfs_lite.exchange.interface import Exchange

logger = logging.getLogger(__name__)


class BitswapExchange(Exchange):
    """Exchange implementation using the Bitswap protocol."""

    def __init__(self, network: BitswapNetwork):
        self.network = network

    async def get_block(self, cid: CID, peers: List) -> Optional[Block]:
        for peer_info in peers:
            response = await self.network.send_want(
                peer_info, cid, want_type=WantType.Block, send_dont_have=True
            )
            if response and response.payload:
                return response.payload[0]
        return None

    async def has_block(self, block: Block) -> None:
        pass  # Future: announce to connected peers
