# ipfs_lite/bitswap/wantlist.py
from dataclasses import dataclass, field
from enum import Enum
from typing import List

from multiformats import CID


class WantType(Enum):
    Block = 0
    Have = 1


@dataclass
class WantlistEntry:
    cid: CID
    priority: int = 1
    cancel: bool = False
    want_type: WantType = WantType.Block
    send_dont_have: bool = False


@dataclass
class Wantlist:
    entries: List[WantlistEntry] = field(default_factory=list)
    full: bool = False

    def add_entry(self, cid: CID, priority: int = 1,
                  want_type: WantType = WantType.Block,
                  send_dont_have: bool = False) -> None:
        entry = WantlistEntry(
            cid=cid, priority=priority,
            want_type=want_type, send_dont_have=send_dont_have,
        )
        self.entries.append(entry)

    def contains(self, cid: CID) -> bool:
        return any(e.cid == cid for e in self.entries)
