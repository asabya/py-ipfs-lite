# tests/test_peer.py
import pytest
from unittest.mock import Mock, AsyncMock

from ipfs_lite.peer import IPFSLitePeer
from ipfs_lite.blockstore.memory import MemoryBlockstore
from ipfs_lite.bitswap.network import BitswapNetwork


def _mock_host(peer_id="QmPeer123"):
    host = Mock()
    host.get_id.return_value = peer_id
    host.get_addrs.return_value = []
    host.set_stream_handler = Mock()
    host.connect = AsyncMock()
    host.new_stream = AsyncMock()
    return host


def test_peer_initialization():
    peer = IPFSLitePeer(host=_mock_host(), blockstore=MemoryBlockstore())
    assert peer.peer_id == "QmPeer123"


def test_peer_has_dag_service():
    peer = IPFSLitePeer(host=_mock_host(), blockstore=MemoryBlockstore())
    from ipfs_lite.dag.service import DAGService
    assert isinstance(peer.dag, DAGService)


async def test_peer_start_registers_handler():
    host = _mock_host()
    peer = IPFSLitePeer(host=host, blockstore=MemoryBlockstore())

    await peer.start()

    host.set_stream_handler.assert_any_call(
        BitswapNetwork.PROTOCOL_ID,
        peer.network.handle_stream,
    )


async def test_peer_connect():
    host = _mock_host()
    peer = IPFSLitePeer(host=host, blockstore=MemoryBlockstore())

    mock_peer_info = Mock()
    await peer.connect(mock_peer_info)

    host.connect.assert_called_once_with(mock_peer_info)
