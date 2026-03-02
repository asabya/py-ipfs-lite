from typing import Optional

from multiformats import CID

from ipfs_lite.block import Block
from ipfs_lite.blockstore.interface import Blockstore


class DAGService:
    """IPLD DAG Service implementation."""

    def __init__(self, blockstore: Blockstore):
        self.blockstore = blockstore

    def get(self, cid: CID) -> Optional[Block]:
        """Retrieve a node by CID."""
        return self.blockstore.get(cid)

    def put(self, block: Block) -> None:
        """Store a node."""
        self.blockstore.put(block)
