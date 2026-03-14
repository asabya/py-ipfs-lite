# ipfs_lite/exchange/bitswap.py
import logging
from typing import Any, List, Optional

from multiformats import CID

from ipfs_lite.block import Block
from ipfs_lite.bitswap.network import BitswapNetwork
from ipfs_lite.exchange.interface import Exchange

logger = logging.getLogger(__name__)


class BitswapExchange(Exchange):
    """Exchange implementation using the Bitswap protocol."""

    def __init__(self, network: BitswapNetwork, dht: Any = None):
        self.network = network
        self.dht = dht

    async def get_block(self, cid: CID, peers: List) -> Optional[Block]:
        targets = list(peers) if peers else self.network.get_connected_peers()
        if not targets:
            logger.warning("No connected peers to fetch block from")
            return None
        response = await self.network.broadcast_want(targets, cid)
        if response and response.payload:
            return response.payload[0]
        return None

    def add_wants(self, cids: list, peers: list) -> None:
        self.network.add_wants(cids)  # peers ignored; sender uses connected peers

    async def wait_for_block(self, cid: CID) -> Optional[Block]:
        return await self.network.wait_for_block(cid)

    async def has_block(self, block: Block) -> None:
        self.network.notify_new_blocks([block])

    def notify_new_blocks(self, blocks: list) -> None:
        self.network.notify_new_blocks(blocks)
