from pathlib import Path
from typing import Optional

from multiformats import CID

from ipfs_lite.block import Block
from ipfs_lite.blockstore.interface import Blockstore


class FilesystemBlockstore(Blockstore):
    """Filesystem-based blockstore implementation."""

    def __init__(self, path: str):
        self._path = Path(path)
        self._path.mkdir(parents=True, exist_ok=True)

    def _cid_to_path(self, cid: CID) -> Path:
        """Convert CID to filesystem path."""
        cid_str = str(cid)
        return self._path / cid_str[:2] / cid_str[2:]

    def get(self, cid: CID) -> Optional[Block]:
        path = self._cid_to_path(cid)
        if not path.exists():
            return None
        data = path.read_bytes()
        return Block(cid=cid, data=data)

    def put(self, block: Block) -> None:
        path = self._cid_to_path(block.cid)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(block.data)

    def has(self, cid: CID) -> bool:
        return self._cid_to_path(cid).exists()

    def all_keys(self) -> list:
        keys = []
        for subdir in self._path.iterdir():
            if subdir.is_dir():
                for entry in subdir.iterdir():
                    if entry.is_file():
                        cid_str = subdir.name + entry.name
                        try:
                            keys.append(CID.decode(cid_str))
                        except Exception:
                            pass
        return keys
