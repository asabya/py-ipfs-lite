# py-ipfs-lite

IPFS-Lite: an embeddable, lightweight IPFS peer for IPLD applications in Python.

## Features

- **CID Support**: Generate and parse IPFS-compatible Content Identifiers
- **Blockstore**: In-memory and filesystem-based storage
- **Bitswap Protocol**: P2P block exchange over libp2p streams
- **DAG Service**: IPLD DAG operations (get, put)
- **UnixFS Files**: Add and retrieve files from the IPFS network

## Installation

```bash
pip install py-ipfs-lite
```

## Quick Start

```python
from ipfs_lite import IPFSLitePeer, MemoryBlockstore

# With an existing libp2p host
peer = IPFSLitePeer(
    host=my_libp2p_host,
    blockstore=MemoryBlockstore(),
)
peer.attach_bitswap()
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

## Status

- [x] Block & CID
- [x] Blockstore (Memory, Filesystem)
- [x] Bitswap Protocol
- [x] DAG Service
- [x] UnixFS File Operations
- [ ] libp2p Integration
- [ ] Integration Tests

## References

- [ipfs-lite (Go)](https://github.com/hsanjuan/ipfs-lite/)
- [py-libp2p](https://github.com/libp2p/py-libp2p)
- [multiformats](https://github.com/hashberg-io/multiformats)
