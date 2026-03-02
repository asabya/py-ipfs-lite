from dataclasses import dataclass

from multiformats import CID, multihash


@dataclass
class Block:
    """Represents a block of data with a CID."""

    cid: CID
    data: bytes

    @property
    def cid_bytes(self) -> bytes:
        """Return CID as bytes."""
        return bytes(self.cid)

    @classmethod
    def from_data(cls, data: bytes, codec: str = "raw") -> "Block":
        """Create a Block from raw data."""
        digest = multihash.digest(data, "sha2-256")
        cid = CID("base32", version=1, codec=codec, digest=digest)
        return cls(cid=cid, data=data)
