# ipfs_lite/unixfs/file.py
import io
import logging
import anyio
from multiformats import CID

from ipfs_lite.block import Block
from ipfs_lite.dag.codecs import (
    decode_dag_pb_all,
    decode_unixfs_data,
    encode_dag_pb,
    encode_unixfs_file,
    encode_unixfs_internal,
)
from ipfs_lite.dag.service import DAGService
from ipfs_lite.unixfs.chunker import Chunker

DEFAULT_MAX_LINKS = 174

logger = logging.getLogger(__name__)


class UnixFSFile:
    """UnixFS file operations."""

    def __init__(self, dag: DAGService, chunk_size: int = 262144):
        self.dag = dag
        self.chunker = Chunker(chunk_size)

    def add_file(self, reader: io.IOBase) -> CID:
        """Add a file and return root CID.

        Uses balanced DAG layout with UnixFS/dag-pb wrapping,
        matching Go's AddFile with RawLeaves=false.
        """
        chunks = list(self.chunker.chunk(reader))

        if len(chunks) == 0:
            # Empty file
            unixfs_bytes = encode_unixfs_file(b"")
            dag_pb_bytes = encode_dag_pb(unixfs_bytes)
            block = Block.from_data(dag_pb_bytes, codec="dag-pb")
            self.dag.put(block)
            return block.cid

        # Build leaf blocks
        leaves = []
        for chunk in chunks:
            unixfs_bytes = encode_unixfs_file(chunk)
            dag_pb_bytes = encode_dag_pb(unixfs_bytes)
            block = Block.from_data(dag_pb_bytes, codec="dag-pb")
            self.dag.put(block)
            leaves.append((block, len(chunk)))

        if len(leaves) == 1:
            return leaves[0][0].cid

        return self._balanced_layout(leaves)

    def _balanced_layout(self, leaves: list[tuple[Block, int]]) -> CID:
        """Build a balanced DAG from leaf blocks, matching Go's balanced.Layout.

        Each entry tracks (block, file_size, cumulative_size) where:
        - file_size: total file data bytes under this node
        - cumulative_size: Go's Node.Size() = len(block.data) + sum(child cumulative sizes)
        """
        max_links = DEFAULT_MAX_LINKS

        # Leaves: cumulative_size = len(block.data) (no children)
        level: list[tuple[Block, int, int]] = [
            (block, fsize, len(block.data)) for block, fsize in leaves
        ]

        while len(level) > 1:
            next_level = []
            for i in range(0, len(level), max_links):
                children = level[i:i + max_links]
                if len(children) == 1:
                    next_level.append(children[0])
                    continue
                links = []
                blocksizes = []
                total_filesize = 0
                total_cum_size = 0
                for child_block, child_filesize, child_cum_size in children:
                    links.append((bytes(child_block.cid), child_cum_size))
                    blocksizes.append(child_filesize)
                    total_filesize += child_filesize
                    total_cum_size += child_cum_size
                unixfs_bytes = encode_unixfs_internal(total_filesize, blocksizes)
                dag_pb_bytes = encode_dag_pb(unixfs_bytes, links)
                block = Block.from_data(dag_pb_bytes, codec="dag-pb")
                self.dag.put(block)
                # This node's cumulative size = own block size + sum of children's cumulative sizes
                cum_size = len(dag_pb_bytes) + total_cum_size
                next_level.append((block, total_filesize, cum_size))
            level = next_level

        return level[0][0].cid

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
