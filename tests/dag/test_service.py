import pytest
from ipfs_lite.block import Block
from ipfs_lite.blockstore.memory import MemoryBlockstore
from ipfs_lite.dag.service import DAGService


def test_dag_service_put_get():
    """Test basic DAG put and get."""
    blockstore = MemoryBlockstore()
    dag = DAGService(blockstore)

    data = b"test node data"
    block = Block.from_data(data, codec="dag-pb")

    dag.put(block)

    retrieved = dag.get(block.cid)

    assert retrieved is not None
    assert retrieved.data == data


def test_dag_service_get_not_found():
    """Test getting non-existent node returns None."""
    blockstore = MemoryBlockstore()
    dag = DAGService(blockstore)

    fake_cid = Block.from_data(b"fake", codec="dag-pb").cid

    result = dag.get(fake_cid)

    assert result is None
