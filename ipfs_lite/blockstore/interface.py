from abc import ABC, abstractmethod
from typing import Optional

from multiformats import CID

from ipfs_lite.block import Block


class Blockstore(ABC):
    """Abstract blockstore interface."""

    @abstractmethod
    def get(self, cid: CID) -> Optional[Block]:
        """Retrieve a block by CID."""
        pass

    @abstractmethod
    def put(self, block: Block) -> None:
        """Store a block."""
        pass

    @abstractmethod
    def has(self, cid: CID) -> bool:
        """Check if a block exists."""
        pass
