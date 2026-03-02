import pytest
from unittest.mock import Mock

from ipfs_lite.peer import IPFSLitePeer
from ipfs_lite.blockstore.memory import MemoryBlockstore
from ipfs_lite.bitswap.protocol import BitswapProtocol


def test_peer_initialization():
    """Test IPFS-Lite peer initializes with components."""
    mock_host = Mock()
    mock_host.get_id.return_value = "QmPeer123"
    mock_host.get_addrs.return_value = []

    peer = IPFSLitePeer(
        host=mock_host,
        blockstore=MemoryBlockstore(),
    )

    assert peer.peer_id == "QmPeer123"


def test_peer_set_protocol_handler():
    """Test peer registers bitswap protocol."""
    mock_host = Mock()
    mock_host.get_id.return_value = "QmPeer123"
    mock_host.set_stream_handler = Mock()

    blockstore = MemoryBlockstore()
    peer = IPFSLitePeer(
        host=mock_host,
        blockstore=blockstore,
    )

    peer.attach_bitswap()

    mock_host.set_stream_handler.assert_called_once()
