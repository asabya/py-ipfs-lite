# ipfs_lite/block_service.py
import asyncio
import logging
from typing import List, Optional

from multiformats import CID

from ipfs_lite.block import Block
from ipfs_lite.blockstore.interface import Blockstore
from ipfs_lite.exchange.interface import Exchange

logger = logging.getLogger(__name__)


class BlockService:
    """Combines local blockstore with optional network exchange."""

    def __init__(self, blockstore: Blockstore, exchange: Optional[Exchange] = None):
        self.blockstore = blockstore
        self.exchange = exchange

    async def get_block(self, cid: CID, peers: List = []) -> Optional[Block]:
        block = self.blockstore.get(cid)
        if block is not None:
            return block
        if self.exchange is not None:
            block = await self.exchange.get_block(cid, peers)
            if block is not None:
                self.blockstore.put(block)
        return block

    def put_block(self, block: Block) -> None:
        self.blockstore.put(block)
        if self.exchange is not None:
            asyncio.create_task(self.exchange.has_block(block))
