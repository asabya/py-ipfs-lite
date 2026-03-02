# tests/test_block_service.py
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from ipfs_lite.block import Block
from ipfs_lite.blockstore.memory import MemoryBlockstore
from ipfs_lite.block_service import BlockService


async def test_get_block_local():
    """BlockService returns block from local store without hitting exchange."""
    store = MemoryBlockstore()
    block = Block.from_data(b"local block", codec="raw")
    store.put(block)

    service = BlockService(store)

    result = await service.get_block(block.cid)

    assert result is not None
    assert result.data == b"local block"


async def test_get_block_from_exchange():
    """BlockService fetches from exchange when not local."""
    store = MemoryBlockstore()
    block = Block.from_data(b"remote block", codec="raw")

    mock_exchange = MagicMock()
    mock_exchange.get_block = AsyncMock(return_value=block)

    service = BlockService(store, exchange=mock_exchange)

    result = await service.get_block(block.cid, peers=["peer1"])

    assert result.data == b"remote block"
    mock_exchange.get_block.assert_called_once_with(block.cid, ["peer1"])


async def test_get_block_caches_after_fetch():
    """Fetched block is cached in local store."""
    store = MemoryBlockstore()
    block = Block.from_data(b"cache me", codec="raw")

    mock_exchange = MagicMock()
    mock_exchange.get_block = AsyncMock(return_value=block)

    service = BlockService(store, exchange=mock_exchange)
    await service.get_block(block.cid, peers=["peer"])

    assert store.has(block.cid) is True


async def test_get_block_not_found():
    """Returns None when neither local nor exchange has block."""
    store = MemoryBlockstore()
    missing_cid = Block.from_data(b"ghost", codec="raw").cid

    mock_exchange = MagicMock()
    mock_exchange.get_block = AsyncMock(return_value=None)

    service = BlockService(store, exchange=mock_exchange)

    result = await service.get_block(missing_cid)

    assert result is None


def test_put_block_stores_locally():
    """put_block saves block to blockstore."""
    store = MemoryBlockstore()
    block = Block.from_data(b"put this", codec="raw")
    service = BlockService(store)

    service.put_block(block)

    assert store.has(block.cid) is True


def test_put_block_no_exchange():
    """put_block works without exchange configured."""
    store = MemoryBlockstore()
    block = Block.from_data(b"no exchange", codec="raw")
    service = BlockService(store)

    service.put_block(block)   # should not raise
