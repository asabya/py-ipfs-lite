# tests/bitswap/test_protocol.py
import pytest

from ipfs_lite.block import Block
from ipfs_lite.blockstore.memory import MemoryBlockstore
from ipfs_lite.bitswap.protocol import BitswapProtocol, BITSWAP_PROTOCOL_ID
from ipfs_lite.bitswap.wantlist import Wantlist, WantType
from ipfs_lite.bitswap.message import Message, MessageType, BlockPresenceType


def test_protocol_id():
    protocol = BitswapProtocol(MemoryBlockstore())
    assert protocol.protocol_id() == BITSWAP_PROTOCOL_ID


async def test_handle_want_block_found():
    blockstore = MemoryBlockstore()
    block = Block.from_data(b"test content", codec="raw")
    blockstore.put(block)

    protocol = BitswapProtocol(blockstore)
    wantlist = Wantlist()
    wantlist.add_entry(block.cid, want_type=WantType.Block)
    message = Message(wantlist=wantlist)

    response = await protocol.handle_message(message)

    assert response is not None
    assert len(response.payload) == 1
    assert response.payload[0].data == b"test content"


async def test_handle_want_block_not_found_with_send_dont_have():
    blockstore = MemoryBlockstore()
    unknown_cid = Block.from_data(b"unknown", codec="raw").cid

    protocol = BitswapProtocol(blockstore)
    wantlist = Wantlist()
    wantlist.add_entry(unknown_cid, want_type=WantType.Block, send_dont_have=True)
    message = Message(wantlist=wantlist)

    response = await protocol.handle_message(message)

    assert response.message_type == MessageType.DONT_HAVE
    assert len(response.block_presences) == 1
    assert response.block_presences[0].type == BlockPresenceType.DontHave


async def test_handle_want_have_found():
    blockstore = MemoryBlockstore()
    block = Block.from_data(b"i have this", codec="raw")
    blockstore.put(block)

    protocol = BitswapProtocol(blockstore)
    wantlist = Wantlist()
    wantlist.add_entry(block.cid, want_type=WantType.Have)
    message = Message(wantlist=wantlist)

    response = await protocol.handle_message(message)

    assert response.message_type == MessageType.HAVE
    assert response.block_presences[0].type == BlockPresenceType.Have


async def test_handle_want_have_not_found():
    blockstore = MemoryBlockstore()
    missing_cid = Block.from_data(b"not here", codec="raw").cid

    protocol = BitswapProtocol(blockstore)
    wantlist = Wantlist()
    wantlist.add_entry(missing_cid, want_type=WantType.Have)
    message = Message(wantlist=wantlist)

    response = await protocol.handle_message(message)

    assert response.message_type == MessageType.DONT_HAVE
    assert response.block_presences[0].type == BlockPresenceType.DontHave
