# libp2p Integration & Integration Tests Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add real py-libp2p networking to py-ipfs-lite with a full BlockService layer, spec-compliant Bitswap 1.2.0 protobuf wire format over msgio-framed streams, and in-process integration tests for block exchange (wantType=Block) and presence checking (wantType=Have).

**Architecture:** Mirror Go ipfs-lite's layered design — `IPFSLitePeer` wires a `BlockService` (local-first lookup + Exchange fallback) on top of the existing `Blockstore`. A new `BitswapNetwork` handles stream I/O (msgio 4-byte BE length prefix + protobuf). `BitswapExchange` dials peers and sends/receives wantlists via `BitswapNetwork`. `DAGService` and `UnixFSFile` become async. All interface changes are acceptable (fresh project).

**Tech Stack:** Python 3.10+, py-libp2p>=0.2.0, protobuf>=4.0.0, grpcio-tools (dev, for proto generation), multiformats, pytest-asyncio

**Design doc:** `docs/plans/2026-03-02-libp2p-integration-design.md`

---

## Task 1: Update Dependencies

**Files:**
- Modify: `pyproject.toml`

### Step 1: Update pyproject.toml

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
    "libp2p>=0.2.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=7.0",
    "pytest-asyncio>=0.21",
    "pytest-cov>=4.0",
    "grpcio-tools>=1.50",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.uv]
dev-dependencies = [
    "pytest>=7.0",
    "pytest-asyncio>=0.21",
    "pytest-cov>=4.0",
    "grpcio-tools>=1.50",
]
```

### Step 2: Install

```bash
uv sync
```

Expected: resolves and installs libp2p and grpcio-tools

### Step 3: Verify libp2p importable

```bash
uv run python -c "import libp2p; print('ok')"
```

Expected: prints `ok`

### Step 4: Commit

```bash
git add pyproject.toml uv.lock
git commit -m "chore: add libp2p and grpcio-tools dependencies"
```

---

## Task 2: Protobuf Schema and Generated Bindings

**Files:**
- Create: `ipfs_lite/bitswap/pb/__init__.py`
- Create: `ipfs_lite/bitswap/pb/message.proto`
- Create: `ipfs_lite/bitswap/pb/message_pb2.py` (generated)
- Test: `tests/bitswap/test_proto.py`

### Step 1: Write the failing test

```python
# tests/bitswap/test_proto.py

def test_proto_message_roundtrip():
    """Test protobuf message serializes and deserializes correctly."""
    from ipfs_lite.bitswap.pb import message_pb2 as pb

    msg = pb.Message()
    wl = pb.Message.Wantlist()
    e = pb.Message.Wantlist.Entry()
    e.block = b"\x01\x55\x12\x20" + b"\xab" * 32   # fake CID bytes
    e.priority = 1
    e.wantType = 0   # Block
    e.sendDontHave = True
    wl.entries.append(e)
    msg.wantlist.CopyFrom(wl)

    data = msg.SerializeToString()
    assert len(data) > 0

    msg2 = pb.Message()
    msg2.ParseFromString(data)
    assert msg2.wantlist.entries[0].block == e.block
    assert msg2.wantlist.entries[0].wantType == 0


def test_proto_block_presence():
    """Test BlockPresence serializes correctly."""
    from ipfs_lite.bitswap.pb import message_pb2 as pb

    msg = pb.Message()
    bp = pb.Message.BlockPresence()
    bp.cid = b"\x01\x55\x12\x20" + b"\xcd" * 32
    bp.type = 0   # Have
    msg.blockPresences.append(bp)

    data = msg.SerializeToString()
    msg2 = pb.Message()
    msg2.ParseFromString(data)
    assert msg2.blockPresences[0].type == 0
```

### Step 2: Run test to verify it fails

```bash
uv run pytest tests/bitswap/test_proto.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'ipfs_lite.bitswap.pb'`

### Step 3: Create pb package and proto file

```bash
mkdir -p ipfs_lite/bitswap/pb
touch ipfs_lite/bitswap/pb/__init__.py
```

Write `ipfs_lite/bitswap/pb/message.proto`:

```proto
syntax = "proto2";

message Message {
  message Wantlist {
    message Entry {
      optional bytes block = 1;
      optional int32 priority = 2;
      optional bool cancel = 3;
      enum WantType {
        Block = 0;
        Have = 1;
      }
      optional WantType wantType = 4;
      optional bool sendDontHave = 5;
    }
    repeated Entry entries = 1;
    optional bool full = 2;
  }

  message Block {
    optional bytes prefix = 1;
    optional bytes data = 2;
  }

  enum BlockPresenceType {
    Have = 0;
    DontHave = 1;
  }

  message BlockPresence {
    optional bytes cid = 1;
    optional BlockPresenceType type = 2;
  }

  optional Wantlist wantlist = 1;
  repeated Block payload = 3;
  repeated BlockPresence blockPresences = 4;
}
```

### Step 4: Generate Python bindings

```bash
uv run python -m grpc_tools.protoc \
    -I ipfs_lite/bitswap/pb \
    --python_out=ipfs_lite/bitswap/pb \
    ipfs_lite/bitswap/pb/message.proto
```

Expected: creates `ipfs_lite/bitswap/pb/message_pb2.py`

Verify:
```bash
ls ipfs_lite/bitswap/pb/
```

Expected: `__init__.py  message.proto  message_pb2.py`

### Step 5: Run test to verify it passes

```bash
uv run pytest tests/bitswap/test_proto.py -v
```

Expected: PASS

### Step 6: Commit

```bash
git add ipfs_lite/bitswap/pb/ tests/bitswap/test_proto.py
git commit -m "feat: add Bitswap protobuf schema and generated bindings"
```

---

## Task 3: Update Bitswap Message Dataclasses

**Files:**
- Modify: `ipfs_lite/bitswap/wantlist.py`
- Modify: `ipfs_lite/bitswap/message.py`
- Modify: `tests/bitswap/test_message.py`

### Step 1: Rewrite wantlist.py

```python
# ipfs_lite/bitswap/wantlist.py
from dataclasses import dataclass, field
from enum import Enum
from typing import List

from multiformats import CID


class WantType(Enum):
    Block = 0
    Have = 1


@dataclass
class WantlistEntry:
    cid: CID
    priority: int = 1
    cancel: bool = False
    want_type: WantType = WantType.Block
    send_dont_have: bool = False


@dataclass
class Wantlist:
    entries: List[WantlistEntry] = field(default_factory=list)
    full: bool = False

    def add_entry(self, cid: CID, priority: int = 1,
                  want_type: WantType = WantType.Block,
                  send_dont_have: bool = False) -> None:
        entry = WantlistEntry(
            cid=cid, priority=priority,
            want_type=want_type, send_dont_have=send_dont_have,
        )
        self.entries.append(entry)

    def contains(self, cid: CID) -> bool:
        return any(e.cid == cid for e in self.entries)
```

### Step 2: Rewrite message.py

```python
# ipfs_lite/bitswap/message.py
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

from multiformats import CID

from ipfs_lite.block import Block
from ipfs_lite.bitswap.wantlist import Wantlist


class MessageType(Enum):
    WANT = "want"
    HAVE = "have"
    BLOCK = "block"
    DONT_HAVE = "dont_have"


class BlockPresenceType(Enum):
    Have = 0
    DontHave = 1


@dataclass
class BlockPresence:
    cid: CID
    type: BlockPresenceType


@dataclass
class Message:
    wantlist: Optional[Wantlist] = None
    payload: List[Block] = field(default_factory=list)
    block_presences: List[BlockPresence] = field(default_factory=list)

    @property
    def message_type(self) -> MessageType:
        if self.wantlist is not None:
            return MessageType.WANT
        if self.payload:
            return MessageType.BLOCK
        if any(bp.type == BlockPresenceType.Have for bp in self.block_presences):
            return MessageType.HAVE
        return MessageType.DONT_HAVE
```

### Step 3: Update test_message.py

```python
# tests/bitswap/test_message.py
import pytest
from multiformats import CID, multihash

from ipfs_lite.block import Block
from ipfs_lite.bitswap.wantlist import Wantlist, WantlistEntry, WantType
from ipfs_lite.bitswap.message import (
    Message, MessageType, BlockPresence, BlockPresenceType,
)


def test_wantlist_entry_creation():
    digest = multihash.digest(b"block data", "sha2-256")
    cid = CID("base32", version=1, codec="raw", digest=digest)

    entry = WantlistEntry(cid=cid, priority=1)

    assert entry.cid == cid
    assert entry.priority == 1
    assert entry.cancel is False
    assert entry.want_type == WantType.Block
    assert entry.send_dont_have is False


def test_wantlist_add_entry():
    wantlist = Wantlist()
    block = Block.from_data(b"wanted block", codec="raw")

    wantlist.add_entry(block.cid, priority=1)

    assert len(wantlist.entries) == 1
    assert wantlist.entries[0].cid == block.cid


def test_wantlist_add_have_entry():
    wantlist = Wantlist()
    block = Block.from_data(b"check presence", codec="raw")

    wantlist.add_entry(block.cid, want_type=WantType.Have, send_dont_have=True)

    assert wantlist.entries[0].want_type == WantType.Have
    assert wantlist.entries[0].send_dont_have is True


def test_message_creation_want():
    block = Block.from_data(b"block1", codec="raw")
    wantlist = Wantlist()
    wantlist.add_entry(block.cid, priority=1)

    message = Message(wantlist=wantlist)

    assert message.message_type == MessageType.WANT


def test_message_creation_block():
    block = Block.from_data(b"payload", codec="raw")
    message = Message(payload=[block])

    assert message.message_type == MessageType.BLOCK
    assert len(message.payload) == 1


def test_message_creation_have_presence():
    digest = multihash.digest(b"some block", "sha2-256")
    cid = CID("base32", version=1, codec="raw", digest=digest)
    presence = BlockPresence(cid=cid, type=BlockPresenceType.Have)
    message = Message(block_presences=[presence])

    assert message.message_type == MessageType.HAVE


def test_message_creation_dont_have_presence():
    digest = multihash.digest(b"missing", "sha2-256")
    cid = CID("base32", version=1, codec="raw", digest=digest)
    presence = BlockPresence(cid=cid, type=BlockPresenceType.DontHave)
    message = Message(block_presences=[presence])

    assert message.message_type == MessageType.DONT_HAVE
```

### Step 4: Run tests

```bash
uv run pytest tests/bitswap/test_message.py -v
```

Expected: PASS (7 tests)

### Step 5: Commit

```bash
git add ipfs_lite/bitswap/wantlist.py ipfs_lite/bitswap/message.py tests/bitswap/test_message.py
git commit -m "feat: update Bitswap message types (WantType, BlockPresence)"
```

---

## Task 4: Update BitswapProtocol

**Files:**
- Modify: `ipfs_lite/bitswap/protocol.py`
- Modify: `tests/bitswap/test_protocol.py`

### Step 1: Update protocol.py

```python
# ipfs_lite/bitswap/protocol.py
import logging
from typing import Optional

from ipfs_lite.blockstore.interface import Blockstore
from ipfs_lite.bitswap.message import (
    Message, MessageType, BlockPresence, BlockPresenceType,
)
from ipfs_lite.bitswap.wantlist import Wantlist, WantType


logger = logging.getLogger(__name__)

BITSWAP_PROTOCOL_ID = "/ipfs/bitswap/1.0.0"


class BitswapProtocol:
    """Bitswap protocol handler — pure logic, no I/O."""

    def __init__(self, blockstore: Blockstore):
        self.blockstore = blockstore

    def protocol_id(self) -> str:
        return BITSWAP_PROTOCOL_ID

    async def handle_message(self, message: Message) -> Optional[Message]:
        if message.wantlist is not None:
            return await self._handle_want(message.wantlist)
        return None

    async def _handle_want(self, wantlist: Wantlist) -> Message:
        blocks = []
        presences = []

        for entry in wantlist.entries:
            block = self.blockstore.get(entry.cid)

            if entry.want_type == WantType.Have:
                ptype = BlockPresenceType.Have if block else BlockPresenceType.DontHave
                presences.append(BlockPresence(cid=entry.cid, type=ptype))
            else:  # WantType.Block
                if block is not None:
                    blocks.append(block)
                elif entry.send_dont_have:
                    presences.append(
                        BlockPresence(cid=entry.cid, type=BlockPresenceType.DontHave)
                    )

        return Message(payload=blocks, block_presences=presences)
```

### Step 2: Update test_protocol.py

```python
# tests/bitswap/test_protocol.py
import pytest

from ipfs_lite.block import Block
from ipfs_lite.blockstore.memory import MemoryBlockstore
from ipfs_lite.bitswap.protocol import BitswapProtocol, BITSWAP_PROTOCOL_ID
from ipfs_lite.bitswap.wantlist import Wantlist, WantType
from ipfs_lite.bitswap.message import Message, MessageType, BlockPresenceType


def test_protocol_id():
    protocol = BitswapProtocol(MemoryBlockstore())
    assert protocol.protocol_id() == BITSWAP_PROTOCOL_ID


async def test_handle_want_block_found():
    blockstore = MemoryBlockstore()
    block = Block.from_data(b"test content", codec="raw")
    blockstore.put(block)

    protocol = BitswapProtocol(blockstore)
    wantlist = Wantlist()
    wantlist.add_entry(block.cid, want_type=WantType.Block)
    message = Message(wantlist=wantlist)

    response = await protocol.handle_message(message)

    assert response is not None
    assert len(response.payload) == 1
    assert response.payload[0].data == b"test content"


async def test_handle_want_block_not_found_with_send_dont_have():
    blockstore = MemoryBlockstore()
    unknown_cid = Block.from_data(b"unknown", codec="raw").cid

    protocol = BitswapProtocol(blockstore)
    wantlist = Wantlist()
    wantlist.add_entry(unknown_cid, want_type=WantType.Block, send_dont_have=True)
    message = Message(wantlist=wantlist)

    response = await protocol.handle_message(message)

    assert response.message_type == MessageType.DONT_HAVE
    assert len(response.block_presences) == 1
    assert response.block_presences[0].type == BlockPresenceType.DontHave


async def test_handle_want_have_found():
    blockstore = MemoryBlockstore()
    block = Block.from_data(b"i have this", codec="raw")
    blockstore.put(block)

    protocol = BitswapProtocol(blockstore)
    wantlist = Wantlist()
    wantlist.add_entry(block.cid, want_type=WantType.Have)
    message = Message(wantlist=wantlist)

    response = await protocol.handle_message(message)

    assert response.message_type == MessageType.HAVE
    assert response.block_presences[0].type == BlockPresenceType.Have


async def test_handle_want_have_not_found():
    blockstore = MemoryBlockstore()
    missing_cid = Block.from_data(b"not here", codec="raw").cid

    protocol = BitswapProtocol(blockstore)
    wantlist = Wantlist()
    wantlist.add_entry(missing_cid, want_type=WantType.Have)
    message = Message(wantlist=wantlist)

    response = await protocol.handle_message(message)

    assert response.message_type == MessageType.DONT_HAVE
    assert response.block_presences[0].type == BlockPresenceType.DontHave
```

### Step 3: Run tests

```bash
uv run pytest tests/bitswap/test_protocol.py -v
```

Expected: PASS (5 tests)

### Step 4: Commit

```bash
git add ipfs_lite/bitswap/protocol.py tests/bitswap/test_protocol.py
git commit -m "feat: update BitswapProtocol with Have/DontHave support"
```

---

## Task 5: BitswapNetwork (msgio framing + protobuf I/O)

**Files:**
- Create: `ipfs_lite/bitswap/network.py`
- Create: `tests/bitswap/test_network.py`

### Step 1: Write the failing test

```python
# tests/bitswap/test_network.py
import struct
import pytest
from multiformats import CID, multihash

from ipfs_lite.block import Block
from ipfs_lite.blockstore.memory import MemoryBlockstore
from ipfs_lite.bitswap.protocol import BitswapProtocol
from ipfs_lite.bitswap.network import BitswapNetwork, encode_message, decode_message
from ipfs_lite.bitswap.wantlist import Wantlist, WantType
from ipfs_lite.bitswap.message import Message, BlockPresenceType


class MockStream:
    """In-memory stream for testing."""

    def __init__(self, data: bytes = b""):
        self._buf = bytearray(data)
        self.written = bytearray()
        self.closed = False

    async def read(self, n: int) -> bytes:
        chunk = bytes(self._buf[:n])
        self._buf = self._buf[n:]
        return chunk

    async def write(self, data: bytes) -> None:
        self.written.extend(data)

    async def close(self) -> None:
        self.closed = True


def _frame(data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + data


def test_encode_decode_roundtrip():
    """Encode a Message to protobuf bytes and decode it back."""
    block = Block.from_data(b"round trip", codec="raw")
    msg = Message(payload=[block])

    encoded = encode_message(msg)
    decoded = decode_message(encoded)

    assert len(decoded.payload) == 1
    assert decoded.payload[0].data == b"round trip"


def test_encode_decode_wantlist():
    """Encode a wantlist message and decode it."""
    block = Block.from_data(b"wanted", codec="raw")
    wl = Wantlist()
    wl.add_entry(block.cid, want_type=WantType.Block, send_dont_have=True)
    msg = Message(wantlist=wl)

    encoded = encode_message(msg)
    decoded = decode_message(encoded)

    assert decoded.wantlist is not None
    assert len(decoded.wantlist.entries) == 1
    assert decoded.wantlist.entries[0].send_dont_have is True


async def test_handle_stream_returns_block():
    """handle_stream reads want, writes block response."""
    blockstore = MemoryBlockstore()
    block = Block.from_data(b"streamed block", codec="raw")
    blockstore.put(block)

    protocol = BitswapProtocol(blockstore)
    network = BitswapNetwork(None, protocol)  # host not needed for handle_stream test

    wl = Wantlist()
    wl.add_entry(block.cid, want_type=WantType.Block)
    msg = Message(wantlist=wl)
    encoded = encode_message(msg)

    stream = MockStream(_frame(encoded))
    await network.handle_stream(stream)

    assert stream.closed is True
    # Parse written response
    resp_len = struct.unpack(">I", stream.written[:4])[0]
    resp_bytes = bytes(stream.written[4:4 + resp_len])
    response = decode_message(resp_bytes)
    assert len(response.payload) == 1
    assert response.payload[0].data == b"streamed block"
```

### Step 2: Run test to verify it fails

```bash
uv run pytest tests/bitswap/test_network.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'ipfs_lite.bitswap.network'`

### Step 3: Write network.py

```python
# ipfs_lite/bitswap/network.py
import logging
import struct
from typing import Optional, Any

from multiformats import CID, multihash
from multiformats import multicodec as mc

from ipfs_lite.block import Block
from ipfs_lite.bitswap.pb import message_pb2 as pb
from ipfs_lite.bitswap.message import (
    Message, BlockPresence, BlockPresenceType,
)
from ipfs_lite.bitswap.wantlist import Wantlist, WantlistEntry, WantType
from ipfs_lite.bitswap.protocol import BitswapProtocol, BITSWAP_PROTOCOL_ID

logger = logging.getLogger(__name__)


# --- varint helpers ---

def _encode_varint(n: int) -> bytes:
    buf = []
    while n > 0x7F:
        buf.append((n & 0x7F) | 0x80)
        n >>= 7
    buf.append(n & 0x7F)
    return bytes(buf)


def _decode_varint(data: bytes, pos: int) -> tuple[int, int]:
    n, shift = 0, 0
    while True:
        b = data[pos]; pos += 1
        n |= (b & 0x7F) << shift
        if not (b & 0x80):
            break
        shift += 7
    return n, pos


# --- CID prefix encode/decode ---

def _cid_prefix(cid: CID) -> bytes:
    return (
        _encode_varint(cid.version)
        + _encode_varint(cid.codec.code)
        + _encode_varint(cid.digest.codec.code)
        + _encode_varint(len(cid.digest.digest))
    )


def _block_from_proto(pb_block) -> Block:
    prefix = bytes(pb_block.prefix)
    data = bytes(pb_block.data)
    pos = 0
    _version, pos = _decode_varint(prefix, pos)
    codec_code, pos = _decode_varint(prefix, pos)
    mh_code, pos = _decode_varint(prefix, pos)
    _mh_len, pos = _decode_varint(prefix, pos)
    codec_name = mc.get(codec_code).name
    mh_name = mc.get(mh_code).name
    digest = multihash.digest(data, mh_name)
    cid = CID("base32", 1, codec_name, digest)
    return Block(cid=cid, data=data)


# --- protobuf encode/decode ---

def encode_message(msg: Message) -> bytes:
    proto = pb.Message()
    if msg.wantlist is not None:
        wl = pb.Message.Wantlist()
        for entry in msg.wantlist.entries:
            e = pb.Message.Wantlist.Entry()
            e.block = bytes(entry.cid)
            e.priority = entry.priority
            e.cancel = entry.cancel
            e.wantType = entry.want_type.value
            e.sendDontHave = entry.send_dont_have
            wl.entries.append(e)
        wl.full = msg.wantlist.full
        proto.wantlist.CopyFrom(wl)
    for block in msg.payload:
        b = pb.Message.Block()
        b.prefix = _cid_prefix(block.cid)
        b.data = block.data
        proto.payload.append(b)
    for presence in msg.block_presences:
        bp = pb.Message.BlockPresence()
        bp.cid = bytes(presence.cid)
        bp.type = presence.type.value
        proto.blockPresences.append(bp)
    return proto.SerializeToString()


def decode_message(data: bytes) -> Message:
    proto = pb.Message()
    proto.ParseFromString(data)

    wantlist = None
    if proto.HasField("wantlist"):
        entries = []
        for e in proto.wantlist.entries:
            cid = CID.decode(e.block)
            entries.append(WantlistEntry(
                cid=cid,
                priority=e.priority,
                cancel=e.cancel,
                want_type=WantType(e.wantType),
                send_dont_have=e.sendDontHave,
            ))
        wantlist = Wantlist(entries=entries, full=proto.wantlist.full)

    payload = [_block_from_proto(b) for b in proto.payload]

    presences = [
        BlockPresence(cid=CID.decode(bp.cid), type=BlockPresenceType(bp.type))
        for bp in proto.blockPresences
    ]

    return Message(wantlist=wantlist, payload=payload, block_presences=presences)


# --- msgio framing ---

async def _read_exactly(stream, n: int) -> bytes:
    data = b""
    while len(data) < n:
        chunk = await stream.read(n - len(data))
        if not chunk:
            raise EOFError("Stream closed unexpectedly")
        data += chunk
    return data


async def _read_msg(stream) -> bytes:
    length_bytes = await _read_exactly(stream, 4)
    length = struct.unpack(">I", length_bytes)[0]
    return await _read_exactly(stream, length)


async def _write_msg(stream, data: bytes) -> None:
    await stream.write(struct.pack(">I", len(data)) + data)


# --- network handler ---

class BitswapNetwork:
    """Handles msgio-framed protobuf Bitswap messages over libp2p streams."""

    PROTOCOL_ID = BITSWAP_PROTOCOL_ID

    def __init__(self, host: Any, protocol: BitswapProtocol):
        self.host = host
        self.protocol = protocol

    async def handle_stream(self, stream) -> None:
        """Inbound stream handler — registered with libp2p host."""
        try:
            data = await _read_msg(stream)
            msg = decode_message(data)
            response = await self.protocol.handle_message(msg)
            if response is not None:
                await _write_msg(stream, encode_message(response))
        except Exception as e:
            logger.error(f"Bitswap stream error: {e}")
        finally:
            await stream.close()

    async def send_want(
        self,
        peer_info: Any,
        cid: CID,
        want_type: WantType = WantType.Block,
        send_dont_have: bool = True,
    ) -> Optional[Message]:
        """Open a stream to peer, send wantlist, return response Message."""
        try:
            stream = await self.host.new_stream(peer_info.peer_id, [self.PROTOCOL_ID])
        except Exception as e:
            logger.error(f"Failed to open stream to {peer_info.peer_id}: {e}")
            return None

        try:
            wl = Wantlist()
            wl.add_entry(cid, want_type=want_type, send_dont_have=send_dont_have)
            msg = Message(wantlist=wl)
            await _write_msg(stream, encode_message(msg))

            data = await _read_msg(stream)
            return decode_message(data)
        except Exception as e:
            logger.error(f"Bitswap send_want error: {e}")
            return None
        finally:
            await stream.close()
```

### Step 4: Run tests

```bash
uv run pytest tests/bitswap/test_network.py -v
```

Expected: PASS (4 tests)

### Step 5: Run all bitswap tests

```bash
uv run pytest tests/bitswap/ -v
```

Expected: all PASS

### Step 6: Commit

```bash
git add ipfs_lite/bitswap/network.py tests/bitswap/test_network.py
git commit -m "feat: add BitswapNetwork with msgio framing and protobuf I/O"
```

---

## Task 6: Exchange Interface

**Files:**
- Create: `ipfs_lite/exchange/__init__.py`
- Create: `ipfs_lite/exchange/interface.py`

### Step 1: Create exchange package

```python
# ipfs_lite/exchange/__init__.py
```

```python
# ipfs_lite/exchange/interface.py
from abc import ABC, abstractmethod
from typing import List, Optional

from multiformats import CID

from ipfs_lite.block import Block


class Exchange(ABC):
    """Abstract interface for block exchange over the network."""

    @abstractmethod
    async def get_block(self, cid: CID, peers: List) -> Optional[Block]:
        """Fetch a block from the network. Returns None if not found."""

    @abstractmethod
    async def has_block(self, block: Block) -> None:
        """Announce to connected peers that we have a block."""
```

### Step 2: Verify importable

```bash
uv run python -c "from ipfs_lite.exchange.interface import Exchange; print('ok')"
```

Expected: prints `ok`

### Step 3: Commit

```bash
git add ipfs_lite/exchange/
git commit -m "feat: add Exchange abstract interface"
```

---

## Task 7: BitswapExchange

**Files:**
- Create: `ipfs_lite/exchange/bitswap.py`
- Create: `tests/exchange/__init__.py`
- Create: `tests/exchange/test_bitswap.py`

### Step 1: Write the failing test

```python
# tests/exchange/test_bitswap.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from multiformats import CID

from ipfs_lite.block import Block
from ipfs_lite.exchange.bitswap import BitswapExchange
from ipfs_lite.bitswap.message import Message, BlockPresenceType, BlockPresence
from ipfs_lite.bitswap.wantlist import WantType


def _make_peer_info(peer_id="QmTest"):
    info = MagicMock()
    info.peer_id = peer_id
    return info


async def test_get_block_success():
    """get_block returns block when network responds."""
    block = Block.from_data(b"exchange block", codec="raw")

    mock_network = MagicMock()
    mock_network.send_want = AsyncMock(
        return_value=Message(payload=[block])
    )

    exchange = BitswapExchange(mock_network)
    peer_info = _make_peer_info()

    result = await exchange.get_block(block.cid, peers=[peer_info])

    assert result is not None
    assert result.data == b"exchange block"
    mock_network.send_want.assert_called_once_with(
        peer_info, block.cid, want_type=WantType.Block, send_dont_have=True
    )


async def test_get_block_not_found():
    """get_block returns None when no peer has block."""
    cid = Block.from_data(b"missing", codec="raw").cid

    mock_network = MagicMock()
    mock_network.send_want = AsyncMock(return_value=None)

    exchange = BitswapExchange(mock_network)

    result = await exchange.get_block(cid, peers=[_make_peer_info()])

    assert result is None


async def test_get_block_tries_multiple_peers():
    """get_block tries each peer until one responds."""
    block = Block.from_data(b"found on second", codec="raw")

    mock_network = MagicMock()
    mock_network.send_want = AsyncMock(
        side_effect=[None, Message(payload=[block])]
    )

    exchange = BitswapExchange(mock_network)
    peers = [_make_peer_info("peer1"), _make_peer_info("peer2")]

    result = await exchange.get_block(block.cid, peers=peers)

    assert result.data == b"found on second"
    assert mock_network.send_want.call_count == 2


async def test_has_block_noop():
    """has_block is a no-op for now (no connected peer tracking)."""
    mock_network = MagicMock()
    exchange = BitswapExchange(mock_network)
    block = Block.from_data(b"announce", codec="raw")

    await exchange.has_block(block)   # should not raise
```

### Step 2: Run test to verify it fails

```bash
uv run pytest tests/exchange/test_bitswap.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'ipfs_lite.exchange.bitswap'`

### Step 3: Write bitswap.py

```python
# ipfs_lite/exchange/bitswap.py
import logging
from typing import List, Optional

from multiformats import CID

from ipfs_lite.block import Block
from ipfs_lite.bitswap.network import BitswapNetwork
from ipfs_lite.bitswap.wantlist import WantType
from ipfs_lite.exchange.interface import Exchange

logger = logging.getLogger(__name__)


class BitswapExchange(Exchange):
    """Exchange implementation using the Bitswap protocol."""

    def __init__(self, network: BitswapNetwork):
        self.network = network

    async def get_block(self, cid: CID, peers: List) -> Optional[Block]:
        for peer_info in peers:
            response = await self.network.send_want(
                peer_info, cid, want_type=WantType.Block, send_dont_have=True
            )
            if response and response.payload:
                return response.payload[0]
        return None

    async def has_block(self, block: Block) -> None:
        pass  # Future: announce to connected peers
```

### Step 4: Create test __init__.py

```bash
touch tests/exchange/__init__.py
```

### Step 5: Run tests

```bash
uv run pytest tests/exchange/test_bitswap.py -v
```

Expected: PASS (4 tests)

### Step 6: Commit

```bash
git add ipfs_lite/exchange/bitswap.py tests/exchange/
git commit -m "feat: add BitswapExchange implementation"
```

---

## Task 8: BlockService

**Files:**
- Create: `ipfs_lite/block_service.py`
- Create: `tests/test_block_service.py`

### Step 1: Write the failing test

```python
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
    service = BlockService(store)  # no exchange

    service.put_block(block)   # should not raise
```

### Step 2: Run test to verify it fails

```bash
uv run pytest tests/test_block_service.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'ipfs_lite.block_service'`

### Step 3: Write block_service.py

```python
# ipfs_lite/block_service.py
import asyncio
import logging
from typing import List, Optional

from multiformats import CID

from ipfs_lite.block import Block
from ipfs_lite.blockstore.interface import Blockstore
from ipfs_lite.exchange.interface import Exchange

logger = logging.getLogger(__name__)


class BlockService:
    """Combines local blockstore with optional network exchange."""

    def __init__(self, blockstore: Blockstore, exchange: Optional[Exchange] = None):
        self.blockstore = blockstore
        self.exchange = exchange

    async def get_block(self, cid: CID, peers: List = []) -> Optional[Block]:
        block = self.blockstore.get(cid)
        if block is not None:
            return block
        if self.exchange is not None:
            block = await self.exchange.get_block(cid, peers)
            if block is not None:
                self.blockstore.put(block)
        return block

    def put_block(self, block: Block) -> None:
        self.blockstore.put(block)
        if self.exchange is not None:
            asyncio.create_task(self.exchange.has_block(block))
```

### Step 4: Run tests

```bash
uv run pytest tests/test_block_service.py -v
```

Expected: PASS (6 tests)

### Step 5: Commit

```bash
git add ipfs_lite/block_service.py tests/test_block_service.py
git commit -m "feat: add BlockService with local-first lookup and exchange fallback"
```

---

## Task 9: Update DAGService

**Files:**
- Modify: `ipfs_lite/dag/service.py`
- Modify: `tests/dag/test_service.py`

### Step 1: Update dag/service.py

```python
# ipfs_lite/dag/service.py
from typing import List, Optional

from multiformats import CID

from ipfs_lite.block import Block
from ipfs_lite.block_service import BlockService


class DAGService:
    """IPLD DAG Service — async get, sync put."""

    def __init__(self, block_service: BlockService):
        self.block_service = block_service

    async def get(self, cid: CID, peers: List = []) -> Optional[Block]:
        """Retrieve a node by CID, fetching from network if needed."""
        return await self.block_service.get_block(cid, peers)

    def put(self, block: Block) -> None:
        """Store a node locally and announce to peers."""
        self.block_service.put_block(block)
```

### Step 2: Update tests/dag/test_service.py

```python
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
```

### Step 3: Run tests

```bash
uv run pytest tests/dag/test_service.py -v
```

Expected: PASS (2 tests)

### Step 4: Commit

```bash
git add ipfs_lite/dag/service.py tests/dag/test_service.py
git commit -m "feat: update DAGService to use BlockService with async get()"
```

---

## Task 10: Update UnixFSFile

**Files:**
- Modify: `ipfs_lite/unixfs/file.py`
- Modify: `tests/unixfs/test_file.py`

### Step 1: Update unixfs/file.py

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
        """Add a file synchronously and return root CID."""
        data = reader.read()
        block = Block.from_data(data, codec="raw")
        self.dag.put(block)
        return block.cid

    async def get_file(self, cid: CID) -> io.BytesIO:
        """Retrieve a file asynchronously."""
        block = await self.dag.get(cid)
        if block is None:
            raise ValueError(f"Block not found: {cid}")
        return io.BytesIO(block.data)
```

Note: `add_file` remains synchronous because `dag.put()` is synchronous. Only `get_file` needs `async` since it calls `dag.get()`.

### Step 2: Update tests/unixfs/test_file.py

```python
# tests/unixfs/test_file.py
import io
import pytest

from ipfs_lite.blockstore.memory import MemoryBlockstore
from ipfs_lite.block_service import BlockService
from ipfs_lite.dag.service import DAGService
from ipfs_lite.unixfs.file import UnixFSFile


def _make_unixfs():
    service = BlockService(MemoryBlockstore())
    dag = DAGService(service)
    return UnixFSFile(dag), dag


def test_add_file_simple():
    unixfs, dag = _make_unixfs()
    content = b"hello world"

    root_cid = unixfs.add_file(io.BytesIO(content))

    assert root_cid is not None


async def test_get_file():
    unixfs, dag = _make_unixfs()
    content = b"test content"
    root_cid = unixfs.add_file(io.BytesIO(content))

    retrieved = await unixfs.get_file(root_cid)

    assert retrieved.read() == content
```

### Step 3: Run tests

```bash
uv run pytest tests/unixfs/test_file.py -v
```

Expected: PASS (2 tests)

### Step 4: Commit

```bash
git add ipfs_lite/unixfs/file.py tests/unixfs/test_file.py
git commit -m "feat: update UnixFSFile with async get_file()"
```

---

## Task 11: Redesign IPFSLitePeer

**Files:**
- Modify: `ipfs_lite/peer.py`
- Modify: `ipfs_lite/__init__.py`
- Modify: `tests/test_peer.py`

### Step 1: Rewrite peer.py

```python
# ipfs_lite/peer.py
import logging
from typing import Any, Optional

from ipfs_lite.blockstore.interface import Blockstore
from ipfs_lite.block_service import BlockService
from ipfs_lite.bitswap.protocol import BitswapProtocol
from ipfs_lite.bitswap.network import BitswapNetwork
from ipfs_lite.exchange.bitswap import BitswapExchange
from ipfs_lite.dag.service import DAGService

logger = logging.getLogger(__name__)


class IPFSLitePeer:
    """Main IPFS-Lite peer — wires blockstore, exchange, dag, and libp2p host."""

    def __init__(self, host: Any, blockstore: Blockstore):
        self.host = host
        self.blockstore = blockstore

        protocol = BitswapProtocol(blockstore)
        self.network = BitswapNetwork(host, protocol)
        self.exchange = BitswapExchange(self.network)
        self.block_service = BlockService(blockstore, self.exchange)
        self.dag = DAGService(self.block_service)

    @property
    def peer_id(self) -> str:
        return str(self.host.get_id())

    async def start(self) -> None:
        """Register Bitswap protocol handler with the libp2p host."""
        self.host.set_stream_handler(
            BitswapNetwork.PROTOCOL_ID,
            self.network.handle_stream,
        )
        logger.info(f"IPFSLitePeer started: {self.peer_id}")

    async def connect(self, peer_info: Any) -> None:
        """Dial a remote peer."""
        await self.host.connect(peer_info)
```

### Step 2: Update __init__.py

```python
# ipfs_lite/__init__.py
"""py-ipfs-lite: IPFS-Lite implementation in Python."""

from ipfs_lite.block import Block
from ipfs_lite.peer import IPFSLitePeer
from ipfs_lite.blockstore.memory import MemoryBlockstore
from ipfs_lite.blockstore.filesystem import FilesystemBlockstore
from ipfs_lite.block_service import BlockService
from ipfs_lite.dag.service import DAGService
from ipfs_lite.bitswap.protocol import BitswapProtocol
from ipfs_lite.bitswap.network import BitswapNetwork
from ipfs_lite.exchange.bitswap import BitswapExchange

__version__ = "0.1.0"

__all__ = [
    "Block",
    "IPFSLitePeer",
    "MemoryBlockstore",
    "FilesystemBlockstore",
    "BlockService",
    "DAGService",
    "BitswapProtocol",
    "BitswapNetwork",
    "BitswapExchange",
]
```

### Step 3: Update tests/test_peer.py

```python
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

    host.set_stream_handler.assert_called_once_with(
        BitswapNetwork.PROTOCOL_ID,
        peer.network.handle_stream,
    )


async def test_peer_connect():
    host = _mock_host()
    peer = IPFSLitePeer(host=host, blockstore=MemoryBlockstore())

    mock_peer_info = Mock()
    await peer.connect(mock_peer_info)

    host.connect.assert_called_once_with(mock_peer_info)
```

### Step 4: Run tests

```bash
uv run pytest tests/test_peer.py -v
```

Expected: PASS (4 tests)

### Step 5: Run full suite (excluding integration)

```bash
uv run pytest tests/ --ignore=tests/integration -v
```

Expected: all PASS

### Step 6: Commit

```bash
git add ipfs_lite/peer.py ipfs_lite/__init__.py tests/test_peer.py
git commit -m "feat: redesign IPFSLitePeer with BlockService layer and async start/connect"
```

---

## Task 12: Integration Tests

**Files:**
- Create: `tests/integration/test_two_peers.py`

These tests require a real libp2p host. Consult `py-libp2p` README and examples at https://github.com/libp2p/py-libp2p for the exact `new_host` and `create_new_key_pair` API if the code below needs adjustment.

### Step 1: Write the failing test

```python
# tests/integration/test_two_peers.py
import pytest
from libp2p import new_host
from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.peer.peerinfo import PeerInfo
from multiaddr import Multiaddr

from ipfs_lite import IPFSLitePeer, MemoryBlockstore, Block


LISTEN_ADDR = Multiaddr("/ip4/127.0.0.1/tcp/0")


async def _make_peer(seed: bytes):
    """Create an IPFSLitePeer with a listening libp2p host."""
    key_pair = create_new_key_pair(seed)
    host = new_host(key_pair)
    peer = IPFSLitePeer(host, MemoryBlockstore())
    return host, peer


async def test_block_exchange():
    """Peer B fetches a block from Peer A over a real TCP loopback stream."""
    host_a, peer_a = await _make_peer(b"a" * 32)
    host_b, peer_b = await _make_peer(b"b" * 32)

    async with host_a.run(listen_addrs=[LISTEN_ADDR]):
        async with host_b.run(listen_addrs=[LISTEN_ADDR]):
            await peer_a.start()
            await peer_b.start()

            # A stores a block
            block = Block.from_data(b"hello libp2p", codec="raw")
            peer_a.dag.put(block)

            # B connects to A
            peer_a_info = PeerInfo(host_a.get_id(), host_a.get_addrs())
            await peer_b.connect(peer_a_info)

            # B fetches block from A
            retrieved = await peer_b.dag.get(block.cid, peers=[peer_a_info])

            assert retrieved is not None
            assert retrieved.data == b"hello libp2p"


async def test_have_response():
    """Peer B checks Have presence, then fetches the actual block."""
    host_a, peer_a = await _make_peer(b"c" * 32)
    host_b, peer_b = await _make_peer(b"d" * 32)

    async with host_a.run(listen_addrs=[LISTEN_ADDR]):
        async with host_b.run(listen_addrs=[LISTEN_ADDR]):
            await peer_a.start()
            await peer_b.start()

            block = Block.from_data(b"check then fetch", codec="raw")
            peer_a.dag.put(block)

            peer_a_info = PeerInfo(host_a.get_id(), host_a.get_addrs())
            await peer_b.connect(peer_a_info)

            from ipfs_lite.bitswap.message import BlockPresenceType
            from ipfs_lite.bitswap.wantlist import WantType

            # Step 1: Have check
            have_response = await peer_b.network.send_want(
                peer_a_info, block.cid, want_type=WantType.Have, send_dont_have=True
            )
            assert have_response is not None
            assert len(have_response.block_presences) == 1
            assert have_response.block_presences[0].type == BlockPresenceType.Have

            # Step 2: Fetch actual block
            block_response = await peer_b.network.send_want(
                peer_a_info, block.cid, want_type=WantType.Block
            )
            assert block_response is not None
            assert len(block_response.payload) == 1
            assert block_response.payload[0].data == b"check then fetch"


async def test_dont_have_response():
    """Peer A sends DontHave when it doesn't have the block."""
    host_a, peer_a = await _make_peer(b"e" * 32)
    host_b, peer_b = await _make_peer(b"f" * 32)

    async with host_a.run(listen_addrs=[LISTEN_ADDR]):
        async with host_b.run(listen_addrs=[LISTEN_ADDR]):
            await peer_a.start()
            await peer_b.start()

            missing_cid = Block.from_data(b"not on A", codec="raw").cid

            peer_a_info = PeerInfo(host_a.get_id(), host_a.get_addrs())
            await peer_b.connect(peer_a_info)

            from ipfs_lite.bitswap.message import BlockPresenceType
            from ipfs_lite.bitswap.wantlist import WantType

            response = await peer_b.network.send_want(
                peer_a_info, missing_cid, want_type=WantType.Have, send_dont_have=True
            )
            assert response is not None
            assert response.block_presences[0].type == BlockPresenceType.DontHave
```

### Step 2: Run to verify tests fail

```bash
uv run pytest tests/integration/test_two_peers.py -v
```

Expected: FAIL (ImportError or connection error — confirms tests need live py-libp2p hosts)

### Step 3: Run integration tests with real hosts

If the py-libp2p API differs from above (e.g. `new_host` is async, or `host.run()` has a different signature), adjust the import paths and call sites to match. Consult py-libp2p examples at https://github.com/libp2p/py-libp2p/tree/main/examples

```bash
uv run pytest tests/integration/test_two_peers.py -v -s
```

Expected: PASS (3 tests)

### Step 4: Run complete test suite

```bash
uv run pytest -v
```

Expected: all PASS

### Step 5: Commit

```bash
git add tests/integration/test_two_peers.py
git commit -m "feat: add integration tests for two-peer block exchange over TCP"
```

---

## Summary

| Task | Component | Key change |
|------|-----------|------------|
| 1 | Dependencies | Add libp2p, grpcio-tools |
| 2 | Protobuf | message.proto + message_pb2.py |
| 3 | Message types | WantType, BlockPresence |
| 4 | BitswapProtocol | Have/DontHave support |
| 5 | BitswapNetwork | msgio + protobuf I/O |
| 6 | Exchange interface | ABC |
| 7 | BitswapExchange | Dial + wantlist |
| 8 | BlockService | Local-first + fallback |
| 9 | DAGService | async get(), uses BlockService |
| 10 | UnixFSFile | async get_file() |
| 11 | IPFSLitePeer | start(), connect(), full wiring |
| 12 | Integration tests | Two real hosts, TCP loopback |
