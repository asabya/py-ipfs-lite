# tests/unixfs/test_file.py
import io
import pytest

from ipfs_lite.blockstore.memory import MemoryBlockstore
from ipfs_lite.block_service import BlockService
from ipfs_lite.dag.service import DAGService
from ipfs_lite.unixfs.file import UnixFSFile


def _make_unixfs():
    service = BlockService(MemoryBlockstore())
    dag = DAGService(service)
    return UnixFSFile(dag), dag


def test_add_file_simple():
    unixfs, dag = _make_unixfs()
    content = b"hello world"

    root_cid = unixfs.add_file(io.BytesIO(content))

    assert root_cid is not None


async def test_get_file():
    unixfs, dag = _make_unixfs()
    content = b"test content"
    root_cid = unixfs.add_file(io.BytesIO(content))

    retrieved = await unixfs.get_file(root_cid)

    assert retrieved.read() == content
