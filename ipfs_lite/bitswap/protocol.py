import logging
from typing import Optional

from ipfs_lite.blockstore.interface import Blockstore
from ipfs_lite.bitswap.message import Message, MessageType
from ipfs_lite.bitswap.wantlist import Wantlist


logger = logging.getLogger(__name__)


class BitswapProtocol:
    """Bitswap protocol handler for IPFS block exchange."""

    PROTOCOL_ID = "/ipfs/bitswap/1.0.0"

    def __init__(self, blockstore: Blockstore):
        self.blockstore = blockstore

    def protocol_id(self) -> str:
        return self.PROTOCOL_ID

    async def handle_message(self, message: Message) -> Optional[Message]:
        """Process a bitswap message and return response."""
        if message.wantlist is not None:
            return await self._handle_want(message.wantlist)
        return None

    async def _handle_want(self, wantlist: Wantlist) -> Message:
        """Handle wantlist entries."""
        blocks = []
        dont_haves = []

        for entry in wantlist.entries:
            block = self.blockstore.get(entry.cid)
            if block is not None:
                blocks.append(block)
            else:
                dont_haves.append(bytes(entry.cid))

        if blocks and not dont_haves:
            return Message(blocks=blocks)
        elif dont_haves and not blocks:
            return Message(dont_haves=dont_haves)
        else:
            return Message(blocks=blocks, dont_haves=dont_haves)
