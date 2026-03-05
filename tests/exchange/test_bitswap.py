# tests/exchange/test_bitswap.py
import pytest
from unittest.mock import AsyncMock, MagicMock

from ipfs_lite.block import Block
from ipfs_lite.exchange.bitswap import BitswapExchange
from ipfs_lite.bitswap.message import Message
from ipfs_lite.bitswap.wantlist import WantType


def _make_peer_info(peer_id="QmTest"):
    info = MagicMock()
    info.peer_id = peer_id
    return info


async def test_get_block_success():
    """get_block returns block when network responds."""
    block = Block.from_data(b"exchange block", codec="raw")

    mock_network = MagicMock()
    mock_network.broadcast_want = AsyncMock(
        return_value=Message(payload=[block])
    )

    exchange = BitswapExchange(mock_network)
    peer_info = _make_peer_info()

    result = await exchange.get_block(block.cid, peers=[peer_info])

    assert result is not None
    assert result.data == b"exchange block"
    mock_network.broadcast_want.assert_called_once_with(
        [peer_info], block.cid, want_type=WantType.Block, send_dont_have=True
    )


async def test_get_block_not_found():
    """get_block returns None when no peer has block."""
    cid = Block.from_data(b"missing", codec="raw").cid

    mock_network = MagicMock()
    mock_network.broadcast_want = AsyncMock(return_value=None)

    exchange = BitswapExchange(mock_network)

    result = await exchange.get_block(cid, peers=[_make_peer_info()])

    assert result is None


async def test_get_block_tries_multiple_peers():
    """get_block broadcasts to all peers and returns first result."""
    block = Block.from_data(b"found on second", codec="raw")

    mock_network = MagicMock()
    mock_network.broadcast_want = AsyncMock(
        return_value=Message(payload=[block])
    )

    exchange = BitswapExchange(mock_network)
    peers = [_make_peer_info("peer1"), _make_peer_info("peer2")]

    result = await exchange.get_block(block.cid, peers=peers)

    assert result is not None
    assert result.data == b"found on second"
    mock_network.broadcast_want.assert_called_once_with(
        peers, block.cid, want_type=WantType.Block, send_dont_have=True
    )


async def test_has_block_noop():
    """has_block is a no-op for now."""
    mock_network = MagicMock()
    exchange = BitswapExchange(mock_network)
    block = Block.from_data(b"announce", codec="raw")

    await exchange.has_block(block)   # should not raise
