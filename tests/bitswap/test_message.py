import pytest
from multiformats import CID, multihash

from ipfs_lite.block import Block
from ipfs_lite.bitswap.wantlist import Wantlist, WantlistEntry, WantlistType
from ipfs_lite.bitswap.message import Message, MessageType


def test_wantlist_entry_creation():
    """Test creating a wantlist entry."""
    digest = multihash.digest(b"block data", "sha2-256")
    cid = CID("base32", version=1, codec="raw", digest=digest)

    entry = WantlistEntry(cid=cid, priority=1)

    assert entry.cid == cid
    assert entry.priority == 1
    assert entry.cancel is False


def test_wantlist_add_entry():
    """Test adding entries to wantlist."""
    wantlist = Wantlist()
    block = Block.from_data(b"wanted block", codec="raw")

    wantlist.add_entry(block.cid, priority=1)

    assert len(wantlist.entries) == 1
    assert wantlist.entries[0].cid == block.cid


def test_message_creation_want():
    """Test creating a want message."""
    block = Block.from_data(b"block1", codec="raw")
    wantlist = Wantlist()
    wantlist.add_entry(block.cid, priority=1)

    message = Message(wantlist=wantlist)

    assert message.message_type == MessageType.WANT


def test_message_creation_block():
    """Test creating a block message."""
    block = Block.from_data(b"payload", codec="raw")
    message = Message(blocks=[block])

    assert message.message_type == MessageType.BLOCK
    assert len(message.blocks) == 1
