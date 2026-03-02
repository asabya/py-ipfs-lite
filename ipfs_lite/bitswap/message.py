from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

from ipfs_lite.block import Block
from ipfs_lite.bitswap.wantlist import Wantlist


class MessageType(Enum):
    WANT = "want"
    HAVE = "have"
    BLOCK = "block"
    DONT_HAVE = "dont_have"


@dataclass
class Message:
    wantlist: Optional[Wantlist] = None
    blocks: List[Block] = field(default_factory=list)
    haves: List[bytes] = field(default_factory=list)
    dont_haves: List[bytes] = field(default_factory=list)

    @property
    def message_type(self) -> MessageType:
        if self.wantlist is not None:
            return MessageType.WANT
        if self.blocks:
            return MessageType.BLOCK
        if self.haves:
            return MessageType.HAVE
        return MessageType.DONT_HAVE
