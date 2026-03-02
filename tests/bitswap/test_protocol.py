import asyncio
import pytest

from ipfs_lite.block import Block
from ipfs_lite.blockstore.memory import MemoryBlockstore
from ipfs_lite.bitswap.protocol import BitswapProtocol
from ipfs_lite.bitswap.wantlist import Wantlist
from ipfs_lite.bitswap.message import Message, MessageType


def test_protocol_handler_registration():
    """Test bitswap protocol ID."""
    blockstore = MemoryBlockstore()
    protocol = BitswapProtocol(blockstore)

    assert protocol.protocol_id() == "/ipfs/bitswap/1.0.0"


async def test_handle_want_block_found():
    """Test handling a want request for a known block."""
    blockstore = MemoryBlockstore()
    block = Block.from_data(b"test content", codec="raw")
    blockstore.put(block)

    protocol = BitswapProtocol(blockstore)
    wantlist = Wantlist()
    wantlist.add_entry(block.cid, priority=1)
    message = Message(wantlist=wantlist)

    response = await protocol.handle_message(message)

    assert response is not None
    assert len(response.blocks) == 1
    assert response.blocks[0].data == b"test content"


async def test_handle_want_block_not_found():
    """Test handling a want request for unknown block."""
    blockstore = MemoryBlockstore()
    unknown_cid = Block.from_data(b"unknown", codec="raw").cid

    protocol = BitswapProtocol(blockstore)
    wantlist = Wantlist()
    wantlist.add_entry(unknown_cid, priority=1)
    message = Message(wantlist=wantlist)

    response = await protocol.handle_message(message)

    assert response.message_type == MessageType.DONT_HAVE
