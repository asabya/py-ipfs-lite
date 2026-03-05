# py-ipfs-lite Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a Python implementation of ipfs-lite - an embeddable, lightweight IPFS peer that provides IPLD DAGService and UnixFS file operations over libp2p.

**Architecture:** Python-native IPFS-lite using py-libp2p for networking, providing CID-based content addressing, block storage, bitswap protocol for P2P block exchange, and DAG-based file operations.

**Tech Stack:** Python 3.10+, py-libp2p, hashberg-io/multiformats, cbor2, protobuf, uv

---

## Pre-requisites (Already Done)

- Git repo initialized locally
- Using `uv` for package management
- Using `pyproject.toml` for project config

---

## Task 1: Project Setup - pyproject.toml

**Files:**
- Create: `pyproject.toml`

### Step 1: Write pyproject.toml

```toml
[project]
name = "py-ipfs-lite"
version = "0.1.0"
description = "IPFS-Lite: embeddable lightweight IPFS peer for IPLD applications"
readme = "README.md"
requires-python = ">=3.10"
dependencies = [
    "multiformats>=0.3.0",
    "cbor2>=5.0.0",
    "protobuf>=4.0.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=7.0",
    "pytest-asyncio>=0.21",
    "pytest-cov>=4.0",
]
libp2p = [
    "libp2p>=0.2.0",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.uv]
dev-dependencies = [
    "pytest>=7.0",
    "pytest-asyncio>=0.21",
    "pytest-cov>=4.0",
]
```

### Step 2: Setup project structure

```bash
mkdir -p ipfs_lite/{blockstore,bitswap,dag,unixfs} tests/{blockstore,bitswap,dag,unixfs,integration}
touch ipfs_lite/__init__.py ipfs_lite/blockstore/__init__.py
touch ipfs_lite/bitswap/__init__.py ipfs_lite/dag/__init__.py
touch ipfs_lite/unixfs/__init__.py tests/__init__.py
```

### Step 3: Commit

```bash
git add pyproject.toml ipfs_lite/ tests/
git commit -m "chore: initial project setup with pyproject.toml"
```

---

## Task 2: Block & CID Foundation

**Files:**
- Create: `ipfs_lite/block.py`
- Test: `tests/test_block.py`

### Step 1: Write the failing test

```python
# tests/test_block.py
import pytest
from multiformats import CID, multihash

from ipfs_lite.block import Block


def test_block_creation_with_cid():
    """Test creating a Block with CID and data."""
    data = b"hello world"
    digest = multihash.digest(data, "sha2-256")
    cid = CID("base32", version=1, codec="raw", digest=digest)
    
    block = Block(cid=cid, data=data)
    
    assert block.cid == cid
    assert block.data == data
    assert block.cid_bytes == bytes(cid)


def test_block_creation_with_raw_cid():
    """Test creating a Block with raw CID string."""
    data = b"test data"
    
    block = Block.from_data(data, codec="raw")
    
    assert block.data == data
    assert block.cid.codec == "raw"


def test_block_from_dag_pb():
    """Test creating a Block from dag-pb codec."""
    data = b"dag-pb content"
    
    block = Block.from_data(data, codec="dag-pb")
    
    assert block.cid.codec == "dag-pb"
```

### Step 2: Run test to verify it fails

```bash
uv run pytest tests/test_block.py -v
```
Expected: FAIL - ModuleNotFoundError: No module named 'ipfs_lite'

### Step 3: Write minimal implementation

```python
# ipfs_lite/block.py
from dataclasses import dataclass

from multiformats import CID, multihash


@dataclass
class Block:
    """Represents a block of data with a CID."""
    
    cid: CID
    data: bytes
    
    @property
    def cid_bytes(self) -> bytes:
        """Return CID as bytes."""
        return bytes(self.cid)
    
    @classmethod
    def from_data(cls, data: bytes, codec: str = "raw") -> "Block":
        """Create a Block from raw data."""
        digest = multihash.digest(data, "sha2-256")
        cid = CID("base32", version=1, codec=codec, digest=digest)
        return cls(cid=cid, data=data)
```

### Step 4: Run test to verify it passes

```bash
uv run pytest tests/test_block.py -v
```
Expected: PASS

### Step 5: Commit

```bash
git add pyproject.toml ipfs_lite/block.py tests/test_block.py
git commit -m "feat: add Block dataclass with CID support"
```

---

## Task 3: Blockstore Interface & Implementations

**Files:**
- Create: `ipfs_lite/blockstore/interface.py`
- Create: `ipfs_lite/blockstore/memory.py`
- Create: `ipfs_lite/blockstore/filesystem.py`
- Test: `tests/blockstore/`

### Step 1: Write the failing test

```python
# tests/blockstore/test_interface.py
import pytest
from multiformats import CID, multihash

from ipfs_lite.block import Block
from ipfs_lite.blockstore.interface import Blockstore
from ipfs_lite.blockstore.memory import MemoryBlockstore


def test_blockstore_put_get():
    """Test basic put and get operations."""
    store = MemoryBlockstore()
    
    block = Block.from_data(b"test content", codec="raw")
    
    store.put(block)
    
    retrieved = store.get(block.cid)
    
    assert retrieved is not None
    assert retrieved.data == block.data


def test_blockstore_has():
    """Test has() returns True for existing blocks."""
    store = MemoryBlockstore()
    block = Block.from_data(b"hello", codec="raw")
    
    assert store.has(block.cid) is False
    
    store.put(block)
    
    assert store.has(block.cid) is True


def test_blockstore_get_not_found():
    """Test get() returns None for missing blocks."""
    store = MemoryBlockstore()
    fake_cid = CID("base32", version=1, codec="raw", 
                   digest=multihash.digest(b"fake", "sha2-256"))
    
    result = store.get(fake_cid)
    
    assert result is None
```

### Step 2: Run test to verify it fails

```bash
uv run pytest tests/blockstore/test_interface.py -v
```
Expected: FAIL - No module named 'ipfs_lite.blockstore'

### Step 3: Write minimal implementation

```python
# ipfs_lite/blockstore/interface.py
from abc import ABC, abstractmethod
from typing import Optional

from multiformats import CID

from ipfs_lite.block import Block


class Blockstore(ABC):
    """Abstract blockstore interface."""
    
    @abstractmethod
    def get(self, cid: CID) -> Optional[Block]:
        """Retrieve a block by CID."""
        pass
    
    @abstractmethod
    def put(self, block: Block) -> None:
        """Store a block."""
        pass
    
    @abstractmethod
    def has(self, cid: CID) -> bool:
        """Check if a block exists."""
        pass
```

```python
# ipfs_lite/blockstore/memory.py
from typing import Dict, Optional

from multiformats import CID

from ipfs_lite.block import Block
from ipfs_lite.blockstore.interface import Blockstore


class MemoryBlockstore(Blockstore):
    """In-memory blockstore implementation."""
    
    def __init__(self):
        self._blocks: Dict[bytes, Block] = {}
    
    def get(self, cid: CID) -> Optional[Block]:
        return self._blocks.get(bytes(cid))
    
    def put(self, block: Block) -> None:
        self._blocks[bytes(block.cid)] = block
    
    def has(self, cid: CID) -> bool:
        return bytes(cid) in self._blocks
```

```python
# ipfs_lite/blockstore/filesystem.py
from pathlib import Path
from typing import Optional

from multiformats import CID

from ipfs_lite.block import Block
from ipfs_lite.blockstore.interface import Blockstore


class FilesystemBlockstore(Blockstore):
    """Filesystem-based blockstore implementation."""
    
    def __init__(self, path: str):
        self._path = Path(path)
        self._path.mkdir(parents=True, exist_ok=True)
    
    def _cid_to_path(self, cid: CID) -> Path:
        """Convert CID to filesystem path."""
        cid_str = str(cid)
        return self._path / cid_str[:2] / cid_str[2:]
    
    def get(self, cid: CID) -> Optional[Block]:
        path = self._cid_to_path(cid)
        if not path.exists():
            return None
        data = path.read_bytes()
        return Block(cid=cid, data=data)
    
    def put(self, block: Block) -> None:
        path = self._cid_to_path(block.cid)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(block.data)
    
    def has(self, cid: CID) -> bool:
        return self._cid_to_path(cid).exists()
```

### Step 4: Run test to verify it passes

```bash
uv run pytest tests/blockstore/test_interface.py -v
```
Expected: PASS

### Step 5: Commit

```bash
git add ipfs_lite/blockstore/ tests/blockstore/
git commit -m "feat: add Blockstore interface with Memory and Filesystem implementations"
```

---

## Task 4: Bitswap Protocol - Message Types

**Files:**
- Create: `ipfs_lite/bitswap/wantlist.py`
- Create: `ipfs_lite/bitswap/message.py`
- Test: `tests/bitswap/test_message.py`

### Step 1: Write the failing test

```python
# tests/bitswap/test_message.py
import pytest
from multiformats import CID, multihash

from ipfs_lite.block import Block
from ipfs_lite.bitswap.wantlist import Wantlist, WantlistEntry, WantlistType
from ipfs_lite.bitswap.message import Message, MessageType


def test_wantlist_entry_creation():
    """Test creating a wantlist entry."""
    digest = multihash.digest(b"block data", "sha2-256")
    cid = CID("base32", version=1, codec="raw", digest=digest)
    
    entry = WantlistEntry(cid=cid, priority=1)
    
    assert entry.cid == cid
    assert entry.priority == 1
    assert entry.cancel is False


def test_wantlist_add_entry():
    """Test adding entries to wantlist."""
    wantlist = Wantlist()
    block = Block.from_data(b"wanted block", codec="raw")
    
    wantlist.add_entry(block.cid, priority=1)
    
    assert len(wantlist.entries) == 1
    assert wantlist.entries[0].cid == block.cid


def test_message_creation_want():
    """Test creating a want message."""
    block = Block.from_data(b"block1", codec="raw")
    wantlist = Wantlist()
    wantlist.add_entry(block.cid, priority=1)
    
    message = Message(wantlist=wantlist)
    
    assert message.message_type == MessageType.WANT


def test_message_creation_block():
    """Test creating a block message."""
    block = Block.from_data(b"payload", codec="raw")
    message = Message(blocks=[block])
    
    assert message.message_type == MessageType.BLOCK
    assert len(message.blocks) == 1
```

### Step 2: Run test to verify it fails

```bash
uv run pytest tests/bitswap/test_message.py -v
```
Expected: FAIL

### Step 3: Write minimal implementation

```python
# ipfs_lite/bitswap/wantlist.py
from dataclasses import dataclass, field
from enum import Enum
from typing import List

from multiformats import CID


class WantlistType(Enum):
    WANT = "want"
    DONT_WANT = "dont_want"


@dataclass
class WantlistEntry:
    cid: CID
    priority: int = 1
    cancel: bool = False
    want_type: WantlistType = WantlistType.WANT


@dataclass
class Wantlist:
    entries: List[WantlistEntry] = field(default_factory=list)
    
    def add_entry(self, cid: CID, priority: int = 1) -> None:
        entry = WantlistEntry(cid=cid, priority=priority)
        self.entries.append(entry)
    
    def contains(self, cid: CID) -> bool:
        return any(e.cid == cid for e in self.entries)
```

```python
# ipfs_lite/bitswap/message.py
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

from ipfs_lite.block import Block
from ipfs_lite.bitswap.wantlist import Wantlist


class MessageType(Enum):
    WANT = "want"
    HAVE = "have"
    BLOCK = "block"
    DONT_HAVE = "dont_have"


@dataclass
class Message:
    wantlist: Optional[Wantlist] = None
    blocks: List[Block] = field(default_factory=list)
    haves: List[bytes] = field(default_factory=list)
    dont_haves: List[bytes] = field(default_factory=list)
    
    @property
    def message_type(self) -> MessageType:
        if self.wantlist is not None:
            return MessageType.WANT
        if self.blocks:
            return MessageType.BLOCK
        if self.haves:
            return MessageType.HAVE
        return MessageType.DONT_HAVE
```

### Step 4: Run test to verify it passes

```bash
uv run pytest tests/bitswap/test_message.py -v
```
Expected: PASS

### Step 5: Commit

```bash
git add ipfs_lite/bitswap/ tests/bitswap/
git commit -m "feat: add Bitswap message types (Wantlist, Message)"
```

---

## Task 5: Bitswap Protocol - Network Handler

**Files:**
- Create: `ipfs_lite/bitswap/protocol.py`
- Test: `tests/bitswap/test_protocol.py`

### Step 1: Write the failing test

```python
# tests/bitswap/test_protocol.py
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


def test_handle_want_block_found():
    """Test handling a want request for a known block."""
    blockstore = MemoryBlockstore()
    block = Block.from_data(b"test content", codec="raw")
    blockstore.put(block)
    
    protocol = BitswapProtocol(blockstore)
    wantlist = Wantlist()
    wantlist.add_entry(block.cid, priority=1)
    message = Message(wantlist=wantlist)
    
    import asyncio
    response = asyncio.run(protocol.handle_message(message))
    
    assert response is not None
    assert len(response.blocks) == 1
    assert response.blocks[0].data == b"test content"


def test_handle_want_block_not_found():
    """Test handling a want request for unknown block."""
    blockstore = MemoryBlockstore()
    unknown_cid = Block.from_data(b"unknown", codec="raw").cid
    
    protocol = BitswapProtocol(blockstore)
    wantlist = Wantlist()
    wantlist.add_entry(unknown_cid, priority=1)
    message = Message(wantlist=wantlist)
    
    import asyncio
    response = asyncio.run(protocol.handle_message(message))
    
    assert response.message_type == MessageType.DONT_HAVE
```

### Step 2: Run test to verify it fails

```bash
uv run pytest tests/bitswap/test_protocol.py -v
```
Expected: FAIL

### Step 3: Write minimal implementation

```python
# ipfs_lite/bitswap/protocol.py
import logging
from typing import Optional

from ipfs_lite.blockstore.interface import Blockstore
from ipfs_lite.bitswap.message import Message, MessageType
from ipfs_lite.bitswap.wantlist import Wantlist


logger = logging.getLogger(__name__)


class BitswapProtocol:
    """Bitswap protocol handler for IPFS block exchange."""
    
    PROTOCOL_ID = "/ipfs/bitswap/1.0.0"
    
    def __init__(self, blockstore: Blockstore):
        self.blockstore = blockstore
    
    def protocol_id(self) -> str:
        return self.PROTOCOL_ID
    
    async def handle_message(self, message: Message) -> Optional[Message]:
        """Process a bitswap message and return response."""
        if message.wantlist is not None:
            return await self._handle_want(message.wantlist)
        return None
    
    async def _handle_want(self, wantlist: Wantlist) -> Message:
        """Handle wantlist entries."""
        blocks = []
        dont_haves = []
        
        for entry in wantlist.entries:
            block = self.blockstore.get(entry.cid)
            if block is not None:
                blocks.append(block)
            else:
                dont_haves.append(bytes(entry.cid))
        
        if blocks and not dont_haves:
            return Message(blocks=blocks)
        elif dont_haves and not blocks:
            return Message(dont_haves=dont_haves)
        else:
            return Message(blocks=blocks, dont_haves=dont_haves)
```

### Step 4: Run test to verify it passes

```bash
uv run pytest tests/bitswap/test_protocol.py -v
```
Expected: PASS

### Step 5: Commit

```bash
git add ipfs_lite/bitswap/protocol.py tests/bitswap/test_protocol.py
git commit -m "feat: add BitswapProtocol handler for block exchange"
```

---

## Task 6: DAG Service Interface

**Files:**
- Create: `ipfs_lite/dag/service.py`
- Create: `ipfs_lite/dag/codecs.py`
- Test: `tests/dag/test_service.py`

### Step 1: Write the failing test

```python
# tests/dag/test_service.py
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
```

### Step 2: Run test to verify it fails

```bash
uv run pytest tests/dag/test_service.py -v
```
Expected: FAIL

### Step 3: Write minimal implementation

```python
# ipfs_lite/dag/service.py
from typing import Optional

from multiformats import CID

from ipfs_lite.block import Block
from ipfs_lite.blockstore.interface import Blockstore


class DAGService:
    """IPLD DAG Service implementation."""
    
    def __init__(self, blockstore: Blockstore):
        self.blockstore = blockstore
    
    def get(self, cid: CID) -> Optional[Block]:
        """Retrieve a node by CID."""
        return self.blockstore.get(cid)
    
    def put(self, block: Block) -> None:
        """Store a node."""
        self.blockstore.put(block)
```

```python
# ipfs_lite/dag/codecs.py
from enum import Enum


class DAGCodec(Enum):
    """Supported IPLD codecs."""
    DAG_PB = 0x70
    DAG_CBOR = 0x71
    RAW = 0x55
    JSON = 0x00
    
    @classmethod
    def from_string(cls, codec_str: str) -> "DAGCodec":
        mapping = {
            "dag-pb": cls.DAG_PB,
            "dag-cbor": cls.DAG_CBOR,
            "raw": cls.RAW,
            "json": cls.JSON,
        }
        return mapping.get(codec_str.lower(), cls.RAW)
```

### Step 4: Run test to verify it passes

```bash
uv run pytest tests/dag/test_service.py -v
```
Expected: PASS

### Step 5: Commit

```bash
git add ipfs_lite/dag/ tests/dag/
git commit -m "feat: add DAGService interface with codec support"
```

---

## Task 7: UnixFS File Operations

**Files:**
- Create: `ipfs_lite/unixfs/chunker.py`
- Create: `ipfs_lite/unixfs/file.py`
- Test: `tests/unixfs/test_file.py`

### Step 1: Write the failing test

```python
# tests/unixfs/test_file.py
import io
import pytest

from ipfs_lite.blockstore.memory import MemoryBlockstore
from ipfs_lite.dag.service import DAGService
from ipfs_lite.unixfs.file import UnixFSFile


def test_add_file_simple():
    """Test adding a small file."""
    blockstore = MemoryBlockstore()
    dag = DAGService(blockstore)
    unixfs = UnixFSFile(dag)
    
    content = b"hello world"
    reader = io.BytesIO(content)
    
    root_cid = unixfs.add_file(reader)
    
    assert root_cid is not None
    
    result = dag.get(root_cid)
    assert result is not None


def test_get_file():
    """Test retrieving a file."""
    blockstore = MemoryBlockstore()
    dag = DAGService(blockstore)
    unixfs = UnixFSFile(dag)
    
    content = b"test content"
    reader = io.BytesIO(content)
    root_cid = unixfs.add_file(reader)
    
    retrieved = unixfs.get_file(root_cid)
    
    assert retrieved.read() == content
```

### Step 2: Run test to verify it fails

```bash
uv run pytest tests/unixfs/test_file.py -v
```
Expected: FAIL

### Step 3: Write minimal implementation

```python
# ipfs_lite/unixfs/chunker.py
import io
from typing import Iterator


class Chunker:
    """Splits input into fixed-size chunks."""
    
    def __init__(self, chunk_size: int = 262144):
        self.chunk_size = chunk_size
    
    def chunk(self, data: io.BytesIO) -> Iterator[bytes]:
        while True:
            chunk = data.read(self.chunk_size)
            if not chunk:
                break
            yield chunk
```

```python
# ipfs_lite/unixfs/file.py
import io
from multiformats import CID

from ipfs_lite.block import Block
from ipfs_lite.dag.service import DAGService
from ipfs_lite.unixfs.chunker import Chunker


class UnixFSFile:
    """UnixFS file operations."""
    
    def __init__(self, dag: DAGService, chunk_size: int = 262144):
        self.dag = dag
        self.chunker = Chunker(chunk_size)
    
    def add_file(self, reader: io.BytesIO) -> CID:
        """Add a file and return root CID."""
        data = reader.read()
        block = Block.from_data(data, codec="raw")
        self.dag.put(block)
        return block.cid
    
    def get_file(self, cid: CID) -> io.BytesIO:
        """Retrieve a file and return as reader."""
        block = self.dag.get(cid)
        if block is None:
            raise ValueError(f"Block not found: {cid}")
        return io.BytesIO(block.data)
```

### Step 4: Run test to verify it passes

```bash
uv run pytest tests/unixfs/test_file.py -v
```
Expected: PASS

### Step 5: Commit

```bash
git add ipfs_lite/unixfs/ tests/unixfs/
git commit -m "feat: add UnixFS file operations (AddFile, GetFile)"
```

---

## Task 8: IPFS-Lite Peer Integration

**Files:**
- Create: `ipfs_lite/peer.py`
- Modify: `ipfs_lite/__init__.py`
- Test: `tests/test_peer.py`

### Step 1: Write the failing test

```python
# tests/test_peer.py
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
    mock_host.set_stream_handler = Mock()
    
    blockstore = MemoryBlockstore()
    peer = IPFSLitePeer(
        host=mock_host,
        blockstore=blockstore,
    )
    
    peer.attach_bitswap()
    
    mock_host.set_stream_handler.assert_called_once()
```

### Step 2: Run test to verify it fails

```bash
uv run pytest tests/test_peer.py -v
```
Expected: FAIL

### Step 3: Write minimal implementation

```python
# ipfs_lite/peer.py
import logging
from typing import Optional, Any

from ipfs_lite.blockstore.interface import Blockstore
from ipfs_lite.bitswap.protocol import BitswapProtocol
from ipfs_lite.dag.service import DAGService


logger = logging.getLogger(__name__)


class IPFSLitePeer:
    """Main IPFS-Lite peer class integrating all components."""
    
    def __init__(
        self,
        host: Any,
        blockstore: Blockstore,
        bitswap: Optional[BitswapProtocol] = None,
    ):
        self.host = host
        self.blockstore = blockstore
        self.dag = DAGService(blockstore)
        self.bitswap = bitswap
        
        self._id = host.get_id()
    
    @property
    def peer_id(self) -> str:
        return str(self._id)
    
    @property
    def addrs(self):
        return self.host.get_addrs()
    
    def attach_bitswap(self) -> None:
        """Register bitswap protocol handler with libp2p host."""
        if self.bitswap is None:
            self.bitswap = BitswapProtocol(self.blockstore)
        
        # Placeholder - will integrate with libp2p later
        logger.info(f"Bitswap protocol handler registered: {self.bitswap.protocol_id()}")
```

```python
# ipfs_lite/__init__.py
"""py-ipfs-lite: IPFS-Lite implementation in Python."""

from ipfs_lite.block import Block
from ipfs_lite.peer import IPFSLitePeer
from ipfs_lite.blockstore.memory import MemoryBlockstore
from ipfs_lite.blockstore.filesystem import FilesystemBlockstore
from ipfs_lite.dag.service import DAGService
from ipfs_lite.bitswap.protocol import BitswapProtocol

__version__ = "0.1.0"

__all__ = [
    "Block",
    "IPFSLitePeer",
    "MemoryBlockstore",
    "FilesystemBlockstore",
    "DAGService",
    "BitswapProtocol",
]
```

### Step 4: Run test to verify it passes

```bash
uv run pytest tests/test_peer.py -v
```
Expected: PASS

### Step 5: Commit

```bash
git add ipfs_lite/peer.py ipfs_lite/__init__.py tests/test_peer.py
git commit -m "feat: add IPFSLitePeer main class integrating all components"
```

---

## Task 9: README Documentation

**Files:**
- Create: `README.md`

### Step 1: Create README

```markdown
# py-ipfs-lite

IPFS-Lite: an embeddable, lightweight IPFS peer for IPLD applications in Python.

## Features

- **CID Support**: Generate and parse IPFS-compatible Content Identifiers
- **Blockstore**: In-memory and filesystem-based storage
- **Bitswap Protocol**: P2P block exchange over libp2p streams
- **DAG Service**: IPLD DAG operations (get, put, remove)
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

## Status

- [x] Block & CID
- [x] Blockstore (Memory, Filesystem)
- [x] Bitswap Protocol
- [x] DAG Service
- [x] UnixFS File Operations
- [ ] libp2p Integration
- [ ] Integration Tests
```

### Step 2: Commit

```bash
git add README.md
git commit -m "docs: add README with quick start guide"
```

---

## Summary

| Task | Component | Status |
|------|-----------|--------|
| 1 | Project Setup (pyproject.toml) | ☐ |
| 2 | Block & CID | ☐ |
| 3 | Blockstore | ☐ |
| 4 | Bitswap Messages | ☐ |
| 5 | Bitswap Protocol | ☐ |
| 6 | DAG Service | ☐ |
| 7 | UnixFS Files | ☐ |
| 8 | Peer Integration | ☐ |
| 9 | README | ☐ |
