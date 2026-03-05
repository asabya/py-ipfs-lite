# py-ipfs-lite

IPFS-Lite: an embeddable, lightweight IPFS peer for IPLD applications in Python.

This is a Python port of [ipfs-lite (Go)](https://github.com/hsanjuan/ipfs-lite), providing an embeddable IPFS peer that runs the minimal setup to provide an IPLD DAGService and UnixFS files addition/retrieval.

## Features

- **CID Support**: Generate and parse IPFS-compatible Content Identifiers (CIDv1, base32, sha2-256)
- **Blockstore**: In-memory and filesystem-based storage
- **Bitswap Protocol**: P2P block exchange over libp2p streams (varint-length-prefixed protobuf)
- **DAG Service**: IPLD DAG operations (get, put) supporting dag-pb, dag-cbor, raw codecs
- **UnixFS Files**: Add and retrieve files from the IPFS network
- **libp2p Integration**: Full integration with py-libp2p for P2P networking

## Architecture

```
IPFSLitePeer          # Entry point; wires all layers together
    │
    ├── DAGService    # IPLD DAG operations; delegates to BlockService
    │
    ├── BlockService  # Combines local Blockstore with network Exchange
    │
    ├── BitswapExchange   # Implements Exchange using BitswapNetwork
    │
    └── BitswapNetwork    # Handles msgio-framed protobuf messages over libp2p streams
            │
            └── Blockstore (Memory or Filesystem)
```

## Installation

```bash
pip install py-ipfs-lite
```

Or install from source:

```bash
uv sync
```

## Quick Start

```python
from ipfs_lite import IPFSLitePeer, MemoryBlockstore

# With an existing libp2p host
peer = IPFSLitePeer(
    host=my_libp2p_host,
    blockstore=MemoryBlockstore(),
)
await peer.start()
```

## Usage

### Working with Blocks

```python
from ipfs_lite import Block, MemoryBlockstore

store = MemoryBlockstore()
block = Block.from_data(b"hello world", codec="raw")
store.put(block)

retrieved = store.get(block.cid)
print(retrieved.data)  # b"hello world"
```

### DAG Operations

```python
from ipfs_lite import Block, MemoryBlockstore, DAGService

dag = DAGService(MemoryBlockstore())
block = Block.from_data(b"node data", codec="dag-pb")
dag.put(block)
node = dag.get(block.cid)
```

### UnixFS Files

```python
import io
from ipfs_lite import MemoryBlockstore, DAGService
from ipfs_lite.unixfs.file import UnixFSFile

dag = DAGService(MemoryBlockstore())
fs = UnixFSFile(dag)

cid = fs.add_file(io.BytesIO(b"file content"))
reader = fs.get_file(cid)
print(reader.read())  # b"file content"
```

### P2P Block Exchange

```python
from ipfs_lite import IPFSLitePeer, MemoryBlockstore

# Create two peers
peer1 = IPFSLitePeer(host=host1, blockstore=MemoryBlockstore())
peer2 = IPFSLitePeer(host=host2, blockstore=MemoryBlockstore())

# Start both peers
await peer1.start()
await peer2.start()

# Connect peer1 to peer2
await peer1.connect(peer2_peer_info)

# Exchange blocks
block = Block.from_data(b"hello from peer1", codec="raw")
await peer1.dag.put(block)

# Get block from peer2's DAG service
retrieved = await peer2.dag.get(block.cid)
```

## Testing

```bash
# Run all tests
uv run pytest

# Run integration tests (requires network)
uv run pytest tests/integration/ -v

# Run a specific test
uv run pytest tests/integration/test_two_peers.py::test_block_exchange -v
```

## Status

- [x] Block & CID
- [x] Blockstore (Memory, Filesystem)
- [x] Bitswap Protocol
- [x] DAG Service
- [x] UnixFS File Operations
- [x] libp2p Integration
- [x] Integration Tests

## References

- [ipfs-lite (Go)](https://github.com/hsanjuan/ipfs-lite/) — Original implementation
- [py-libp2p](https://github.com/libp2p/py-libp2p) — Python libp2p implementation
- [multiformats](https://github.com/hashberg-io/multiformats) — Python multiformats
- [IPFS Bitswap Spec](https://github.com/ipfs/specs/tree/main/bitswap)
