# ipfs_lite/bitswap/message.py
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

from multiformats import CID

from ipfs_lite.block import Block
from ipfs_lite.bitswap.wantlist import Wantlist


class MessageType(Enum):
    WANT = "want"
    HAVE = "have"
    BLOCK = "block"
    DONT_HAVE = "dont_have"


class BlockPresenceType(Enum):
    Have = 0
    DontHave = 1


@dataclass
class BlockPresence:
    cid: CID
    type: BlockPresenceType


@dataclass
class Message:
    wantlist: Optional[Wantlist] = None
    payload: List[Block] = field(default_factory=list)
    block_presences: List[BlockPresence] = field(default_factory=list)

    @property
    def message_type(self) -> MessageType:
        if self.wantlist is not None:
            return MessageType.WANT
        if self.payload:
            return MessageType.BLOCK
        if any(bp.type == BlockPresenceType.Have for bp in self.block_presences):
            return MessageType.HAVE
        return MessageType.DONT_HAVE
