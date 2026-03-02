from dataclasses import dataclass, field
from enum import Enum
from typing import List

from multiformats import CID


class WantlistType(Enum):
    WANT = "want"
    DONT_WANT = "dont_want"


@dataclass
class WantlistEntry:
    cid: CID
    priority: int = 1
    cancel: bool = False
    want_type: WantlistType = WantlistType.WANT


@dataclass
class Wantlist:
    entries: List[WantlistEntry] = field(default_factory=list)

    def add_entry(self, cid: CID, priority: int = 1) -> None:
        entry = WantlistEntry(cid=cid, priority=priority)
        self.entries.append(entry)

    def contains(self, cid: CID) -> bool:
        return any(e.cid == cid for e in self.entries)
