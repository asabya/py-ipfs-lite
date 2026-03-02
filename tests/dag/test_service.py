# tests/dag/test_service.py
import pytest
from ipfs_lite.block import Block
from ipfs_lite.blockstore.memory import MemoryBlockstore
from ipfs_lite.block_service import BlockService
from ipfs_lite.dag.service import DAGService


async def test_dag_service_put_get():
    service = BlockService(MemoryBlockstore())
    dag = DAGService(service)

    data = b"test node data"
    block = Block.from_data(data, codec="dag-pb")
    dag.put(block)

    retrieved = await dag.get(block.cid)

    assert retrieved is not None
    assert retrieved.data == data


async def test_dag_service_get_not_found():
    service = BlockService(MemoryBlockstore())
    dag = DAGService(service)

    fake_cid = Block.from_data(b"fake", codec="dag-pb").cid

    result = await dag.get(fake_cid)

    assert result is None
