# tests/bitswap/test_message.py
import pytest
from multiformats import CID, multihash

from ipfs_lite.block import Block
from ipfs_lite.bitswap.wantlist import Wantlist, WantlistEntry, WantType
from ipfs_lite.bitswap.message import (
    Message, MessageType, BlockPresence, BlockPresenceType,
)


def test_wantlist_entry_creation():
    digest = multihash.digest(b"block data", "sha2-256")
    cid = CID("base32", version=1, codec="raw", digest=digest)

    entry = WantlistEntry(cid=cid, priority=1)

    assert entry.cid == cid
    assert entry.priority == 1
    assert entry.cancel is False
    assert entry.want_type == WantType.Block
    assert entry.send_dont_have is False


def test_wantlist_add_entry():
    wantlist = Wantlist()
    block = Block.from_data(b"wanted block", codec="raw")

    wantlist.add_entry(block.cid, priority=1)

    assert len(wantlist.entries) == 1
    assert wantlist.entries[0].cid == block.cid


def test_wantlist_add_have_entry():
    wantlist = Wantlist()
    block = Block.from_data(b"check presence", codec="raw")

    wantlist.add_entry(block.cid, want_type=WantType.Have, send_dont_have=True)

    assert wantlist.entries[0].want_type == WantType.Have
    assert wantlist.entries[0].send_dont_have is True


def test_message_creation_want():
    block = Block.from_data(b"block1", codec="raw")
    wantlist = Wantlist()
    wantlist.add_entry(block.cid, priority=1)

    message = Message(wantlist=wantlist)

    assert message.message_type == MessageType.WANT


def test_message_creation_block():
    block = Block.from_data(b"payload", codec="raw")
    message = Message(payload=[block])

    assert message.message_type == MessageType.BLOCK
    assert len(message.payload) == 1


def test_message_creation_have_presence():
    digest = multihash.digest(b"some block", "sha2-256")
    cid = CID("base32", version=1, codec="raw", digest=digest)
    presence = BlockPresence(cid=cid, type=BlockPresenceType.Have)
    message = Message(block_presences=[presence])

    assert message.message_type == MessageType.HAVE


def test_message_creation_dont_have_presence():
    digest = multihash.digest(b"missing", "sha2-256")
    cid = CID("base32", version=1, codec="raw", digest=digest)
    presence = BlockPresence(cid=cid, type=BlockPresenceType.DontHave)
    message = Message(block_presences=[presence])

    assert message.message_type == MessageType.DONT_HAVE
