"""py-ipfs-lite: IPFS-Lite implementation in Python."""

from ipfs_lite.block import Block
from ipfs_lite.peer import IPFSLitePeer
from ipfs_lite.blockstore.memory import MemoryBlockstore
from ipfs_lite.blockstore.filesystem import FilesystemBlockstore
from ipfs_lite.dag.service import DAGService
from ipfs_lite.bitswap.protocol import BitswapProtocol

__version__ = "0.1.0"

__all__ = [
    "Block",
    "IPFSLitePeer",
    "MemoryBlockstore",
    "FilesystemBlockstore",
    "DAGService",
    "BitswapProtocol",
]
