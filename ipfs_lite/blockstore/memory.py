from typing import Dict, Optional

from multiformats import CID

from ipfs_lite.block import Block
from ipfs_lite.blockstore.interface import Blockstore


class MemoryBlockstore(Blockstore):
    """In-memory blockstore implementation."""

    def __init__(self):
        self._blocks: Dict[bytes, Block] = {}

    def get(self, cid: CID) -> Optional[Block]:
        return self._blocks.get(bytes(cid))

    def put(self, block: Block) -> None:
        self._blocks[bytes(block.cid)] = block

    def has(self, cid: CID) -> bool:
        return bytes(cid) in self._blocks
