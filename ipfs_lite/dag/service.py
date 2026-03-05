# ipfs_lite/dag/service.py
from typing import List, Optional

from multiformats import CID

from ipfs_lite.block import Block
from ipfs_lite.block_service import BlockService


class DAGService:
    """IPLD DAG Service — async get, sync put."""

    def __init__(self, block_service: BlockService):
        self.block_service = block_service

    async def get(self, cid: CID, peers: List = []) -> Optional[Block]:
        """Retrieve a node by CID, fetching from network if needed."""
        return await self.block_service.get_block(cid, peers)

    def put(self, block: Block) -> None:
        """Store a node locally and announce to peers."""
        self.block_service.put_block(block)

    def want(self, cids: list, peers: list = []) -> None:
        """Queue CIDs for background want-sender."""
        if self.block_service.exchange is not None:
            self.block_service.exchange.add_wants(cids, peers)

    async def wait_for_block(self, cid: CID) -> Optional[Block]:
        """Wait for block event (registered via want()), check blockstore on arrival."""
        block = self.block_service.blockstore.get(cid)
        if block:
            return block
        if self.block_service.exchange is not None:
            block = await self.block_service.exchange.wait_for_block(cid)
            if block is not None:
                self.block_service.blockstore.put(block)
        return block
