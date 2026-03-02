import io
from multiformats import CID

from ipfs_lite.block import Block
from ipfs_lite.dag.service import DAGService
from ipfs_lite.unixfs.chunker import Chunker


class UnixFSFile:
    """UnixFS file operations."""

    def __init__(self, dag: DAGService, chunk_size: int = 262144):
        self.dag = dag
        self.chunker = Chunker(chunk_size)

    def add_file(self, reader: io.BytesIO) -> CID:
        """Add a file and return root CID."""
        data = reader.read()
        block = Block.from_data(data, codec="raw")
        self.dag.put(block)
        return block.cid

    def get_file(self, cid: CID) -> io.BytesIO:
        """Retrieve a file and return as reader."""
        block = self.dag.get(cid)
        if block is None:
            raise ValueError(f"Block not found: {cid}")
        return io.BytesIO(block.data)
