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
