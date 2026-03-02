import pytest
from multiformats import CID, multihash

from ipfs_lite.block import Block
from ipfs_lite.blockstore.interface import Blockstore
from ipfs_lite.blockstore.memory import MemoryBlockstore


def test_blockstore_put_get():
    """Test basic put and get operations."""
    store = MemoryBlockstore()

    block = Block.from_data(b"test content", codec="raw")

    store.put(block)

    retrieved = store.get(block.cid)

    assert retrieved is not None
    assert retrieved.data == block.data


def test_blockstore_has():
    """Test has() returns True for existing blocks."""
    store = MemoryBlockstore()
    block = Block.from_data(b"hello", codec="raw")

    assert store.has(block.cid) is False

    store.put(block)

    assert store.has(block.cid) is True


def test_blockstore_get_not_found():
    """Test get() returns None for missing blocks."""
    store = MemoryBlockstore()
    fake_cid = CID("base32", version=1, codec="raw",
                   digest=multihash.digest(b"fake", "sha2-256"))

    result = store.get(fake_cid)

    assert result is None
