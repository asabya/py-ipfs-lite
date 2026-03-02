# ipfs_lite/bitswap/protocol.py
import logging
from typing import Optional

from ipfs_lite.blockstore.interface import Blockstore
from ipfs_lite.bitswap.message import (
    Message, BlockPresence, BlockPresenceType,
)
from ipfs_lite.bitswap.wantlist import Wantlist, WantType


logger = logging.getLogger(__name__)

BITSWAP_PROTOCOL_ID = "/ipfs/bitswap/1.0.0"


class BitswapProtocol:
    """Bitswap protocol handler — pure logic, no I/O."""

    def __init__(self, blockstore: Blockstore):
        self.blockstore = blockstore

    def protocol_id(self) -> str:
        return BITSWAP_PROTOCOL_ID

    async def handle_message(self, message: Message) -> Optional[Message]:
        if message.wantlist is not None:
            return await self._handle_want(message.wantlist)
        return None

    async def _handle_want(self, wantlist: Wantlist) -> Message:
        blocks = []
        presences = []

        for entry in wantlist.entries:
            block = self.blockstore.get(entry.cid)

            if entry.want_type == WantType.Have:
                ptype = BlockPresenceType.Have if block else BlockPresenceType.DontHave
                presences.append(BlockPresence(cid=entry.cid, type=ptype))
            else:  # WantType.Block
                if block is not None:
                    blocks.append(block)
                elif entry.send_dont_have:
                    presences.append(
                        BlockPresence(cid=entry.cid, type=BlockPresenceType.DontHave)
                    )

        return Message(payload=blocks, block_presences=presences)
