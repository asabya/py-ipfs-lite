import io
import pytest

from ipfs_lite.blockstore.memory import MemoryBlockstore
from ipfs_lite.dag.service import DAGService
from ipfs_lite.unixfs.file import UnixFSFile


def test_add_file_simple():
    """Test adding a small file."""
    blockstore = MemoryBlockstore()
    dag = DAGService(blockstore)
    unixfs = UnixFSFile(dag)

    content = b"hello world"
    reader = io.BytesIO(content)

    root_cid = unixfs.add_file(reader)

    assert root_cid is not None

    result = dag.get(root_cid)
    assert result is not None


def test_get_file():
    """Test retrieving a file."""
    blockstore = MemoryBlockstore()
    dag = DAGService(blockstore)
    unixfs = UnixFSFile(dag)

    content = b"test content"
    reader = io.BytesIO(content)
    root_cid = unixfs.add_file(reader)

    retrieved = unixfs.get_file(root_cid)

    assert retrieved.read() == content
