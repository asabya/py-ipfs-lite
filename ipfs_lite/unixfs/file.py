# ipfs_lite/unixfs/file.py
import io
import logging
import anyio
from multiformats import CID

from ipfs_lite.block import Block
from ipfs_lite.dag.codecs import decode_dag_pb_all, decode_unixfs_data
from ipfs_lite.dag.service import DAGService
from ipfs_lite.unixfs.chunker import Chunker

logger = logging.getLogger(__name__)


class UnixFSFile:
    """UnixFS file operations."""

    def __init__(self, dag: DAGService, chunk_size: int = 262144):
        self.dag = dag
        self.chunker = Chunker(chunk_size)

    def add_file(self, reader: io.BytesIO) -> CID:
        """Add a file synchronously and return root CID."""
        data = reader.read()
        block = Block.from_data(data, codec="raw")
        self.dag.put(block)
        return block.cid

    async def _collect(self, cid: CID, peers: list) -> bytes:
        logger.info(f"Fetching block {cid}")
        block = await self.dag.get(cid, peers=peers)
        if block is None:
            raise ValueError(f"Block not found: {cid}")
        logger.info(f"Got block {cid} ({len(block.data)} bytes, codec={block.cid.codec.name})")
        return await self._process_block(block, peers)

    async def _process_block(self, block: Block, peers: list) -> bytes:
        if block.cid.codec.name != "dag-pb":
            return block.data
        unixfs_bytes, link_cids = decode_dag_pb_all(block.data)
        inline = decode_unixfs_data(unixfs_bytes) if unixfs_bytes else b""
        if not link_cids:
            return inline
        all_cids = [CID.decode(cb) for cb in link_cids]
        logger.info(f"Queuing {len(all_cids)} child wants")
        # Enqueue ALL child CIDs — background sender will flush in one message
        self.dag.want(all_cids, peers)

        chunks: list[bytes] = [b""] * len(all_cids)

        async def fetch_link(i: int, child_cid: CID) -> None:
            child_block = await self.dag.wait_for_block(child_cid)
            if child_block is None:
                raise ValueError(f"Block not found: {child_cid}")
            chunks[i] = await self._process_block(child_block, peers)

        async with anyio.create_task_group() as tg:
            for i, child_cid in enumerate(all_cids):
                tg.start_soon(fetch_link, i, child_cid)

        return inline + b"".join(chunks)

    async def get_file(self, cid: CID, peers: list = []) -> io.BytesIO:
        """Retrieve a file asynchronously, recursively traversing the UnixFS DAG."""
        return io.BytesIO(await self._collect(cid, peers))
