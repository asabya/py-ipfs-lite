# ipfs_lite/exchange/interface.py
from abc import ABC, abstractmethod
from typing import List, Optional

from multiformats import CID

from ipfs_lite.block import Block


class Exchange(ABC):
    """Abstract interface for block exchange over the network."""

    @abstractmethod
    async def get_block(self, cid: CID, peers: List) -> Optional[Block]:
        """Fetch a block from the network. Returns None if not found."""

    @abstractmethod
    async def has_block(self, block: Block) -> None:
        """Announce to connected peers that we have a block."""

    @abstractmethod
    def notify_new_blocks(self, blocks: list) -> None:
        """Notify the exchange that new blocks are available locally."""
