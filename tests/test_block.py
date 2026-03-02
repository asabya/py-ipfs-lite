import pytest
from multiformats import CID, multihash

from ipfs_lite.block import Block


def test_block_creation_with_cid():
    """Test creating a Block with CID and data."""
    data = b"hello world"
    digest = multihash.digest(data, "sha2-256")
    cid = CID("base32", version=1, codec="raw", digest=digest)

    block = Block(cid=cid, data=data)

    assert block.cid == cid
    assert block.data == data
    assert block.cid_bytes == bytes(cid)


def test_block_creation_with_raw_cid():
    """Test creating a Block with raw CID string."""
    data = b"test data"

    block = Block.from_data(data, codec="raw")

    assert block.data == data
    assert block.cid.codec.name == "raw"


def test_block_from_dag_pb():
    """Test creating a Block from dag-pb codec."""
    data = b"dag-pb content"

    block = Block.from_data(data, codec="dag-pb")

    assert block.cid.codec.name == "dag-pb"
