# libp2p Integration & Integration Tests Design

**Date:** 2026-03-02
**Scope:** Add real py-libp2p networking to py-ipfs-lite with a full BlockService layer, protobuf Bitswap wire format, and in-process integration tests.

---

## Goals

- Mirror Go ipfs-lite's layered architecture (BlockService + Exchange abstraction)
- Spec-compliant Bitswap 1.2.0 over real libp2p streams (protobuf + msgio framing)
- Integration tests: two in-process `IPFSLitePeer` instances exchange blocks over TCP loopback
- Test both `wantType=Block` (fetch data) and `wantType=Have` (check presence → BlockPresence response)
- No backward compatibility constraints — interface changes are acceptable

---

## Architecture

```
IPFSLitePeer
  ├─ async start()          registers stream handlers with libp2p host
  ├─ async connect(peer)    dials remote peer
  └─ DAGService  (async get/put)
       └─ BlockService
            ├─ Blockstore              local storage (unchanged)
            └─ Exchange (ABC)
                 └─ BitswapExchange
                      └─ BitswapNetwork
                           ├─ msgio framing (4-byte BE length prefix)
                           └─ protobuf encode/decode
```

---

## Section 1: New Files

| Path | Purpose |
|------|---------|
| `ipfs_lite/bitswap/pb/message.proto` | Bitswap 1.2.0 proto schema |
| `ipfs_lite/bitswap/pb/message_pb2.py` | Generated protobuf bindings (checked in) |
| `ipfs_lite/bitswap/network.py` | `BitswapNetwork`: msgio framing + proto I/O over `INetStream` |
| `ipfs_lite/exchange/interface.py` | `Exchange` ABC |
| `ipfs_lite/exchange/bitswap.py` | `BitswapExchange`: dials peers, sends wantlists, handles responses |
| `ipfs_lite/block_service.py` | `BlockService`: local-first lookup with exchange fallback |
| `tests/integration/test_two_peers.py` | End-to-end integration tests |

---

## Section 2: Updated Files

| Path | Change |
|------|--------|
| `ipfs_lite/bitswap/wantlist.py` | Rename `WantlistType` values to `Block`/`Have`; add `send_dont_have: bool` to `WantlistEntry` |
| `ipfs_lite/bitswap/message.py` | Add `BlockPresence`, `BlockPresenceType`; rename `blocks` → `payload` (CIDv1) |
| `ipfs_lite/bitswap/protocol.py` | Handle `wantType=Have` → return `BlockPresence`; handle `send_dont_have` |
| `ipfs_lite/dag/service.py` | Accept `BlockService`; make `get()` async |
| `ipfs_lite/unixfs/file.py` | Make `add_file()`/`get_file()` async |
| `ipfs_lite/peer.py` | Full redesign: wire all components; add `start()`, `connect()` |
| `ipfs_lite/__init__.py` | Export new public types |
| `pyproject.toml` | Add `libp2p>=0.2.0`; add `grpcio-tools` as dev dependency |

---

## Section 3: Protobuf Schema

```proto
syntax = "proto2";

message Message {
  message Wantlist {
    message Entry {
      optional bytes block = 1;
      optional int32 priority = 2;
      optional bool cancel = 3;
      enum WantType { Block = 0; Have = 1; }
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

  enum BlockPresenceType { Have = 0; DontHave = 1; }

  message BlockPresence {
    optional bytes cid = 1;
    optional BlockPresenceType type = 2;
  }

  optional Wantlist wantlist = 1;
  repeated Block payload = 3;
  repeated BlockPresence blockPresences = 4;
}
```

`message_pb2.py` is generated via `grpcio-tools` and checked in so users need no build tooling.

---

## Section 4: Stream Framing

Bitswap uses `msgio` — 4-byte big-endian unsigned int length prefix:

```
┌──────────────┬────────────────────────┐
│  uint32 BE   │  protobuf Message bytes │
│  (4 bytes)   │  (N bytes)              │
└──────────────┴────────────────────────┘
```

`BitswapNetwork` reads/writes with this framing on every `INetStream`.

---

## Section 5: BlockService + Exchange

```python
class Exchange(ABC):
    async def get_block(self, cid: CID, peers: List[PeerInfo]) -> Optional[Block]: ...
    async def has_block(self, block: Block) -> None: ...

class BlockService:
    async def get_block(self, cid, peers=[]) -> Optional[Block]:
        block = self.blockstore.get(cid)           # local first
        if block is None and self.exchange:
            block = await self.exchange.get_block(cid, peers)
            if block:
                self.blockstore.put(block)         # cache
        return block

    def put_block(self, block: Block) -> None:
        self.blockstore.put(block)
        if self.exchange:
            asyncio.create_task(self.exchange.has_block(block))
```

---

## Section 6: BitswapProtocol — Have Handling

```python
async def _handle_want(self, wantlist: Wantlist) -> Message:
    blocks, presences = [], []
    for entry in wantlist.entries:
        block = self.blockstore.get(entry.cid)
        if entry.want_type == WantType.Have:
            t = BlockPresenceType.Have if block else BlockPresenceType.DontHave
            presences.append(BlockPresence(cid=entry.cid, type=t))
        else:  # WantType.Block
            if block:
                blocks.append(block)
            elif entry.send_dont_have:
                presences.append(BlockPresence(cid=entry.cid, type=BlockPresenceType.DontHave))
    return Message(payload=blocks, block_presences=presences)
```

---

## Section 7: Updated IPFSLitePeer

```python
class IPFSLitePeer:
    def __init__(self, host: BasicHost, blockstore: Blockstore):
        self.host = host
        self.blockstore = blockstore
        self.network = BitswapNetwork(host, BitswapProtocol(blockstore))
        self.exchange = BitswapExchange(self.network)
        self.block_service = BlockService(blockstore, self.exchange)
        self.dag = DAGService(self.block_service)

    async def start(self) -> None:
        self.host.set_stream_handler(BITSWAP_PROTOCOL_ID, self.network.handle_stream)

    async def connect(self, peer_info: PeerInfo) -> None:
        await self.host.connect(peer_info)
```

---

## Section 8: Integration Tests

**`tests/integration/test_two_peers.py`:**

```python
async def test_block_exchange():
    host_a = new_host(create_new_key_pair(b"seed_a" * 16))
    host_b = new_host(create_new_key_pair(b"seed_b" * 16))

    peer_a = IPFSLitePeer(host_a, MemoryBlockstore())
    peer_b = IPFSLitePeer(host_b, MemoryBlockstore())
    await peer_a.start()
    await peer_b.start()

    block = Block.from_data(b"hello libp2p", codec="raw")
    peer_a.dag.put(block)

    await peer_b.connect(info_from_p2p_addr(host_a.get_addrs()[0]))
    retrieved = await peer_b.dag.get(block.cid, peers=[host_a.get_addrs()[0]])
    assert retrieved.data == b"hello libp2p"

async def test_have_response():
    # Peer B sends wantType=Have → gets BlockPresence(Have)
    # Peer B sends wantType=Block → gets actual block data
    ...
```

---

## References

- [ipfs-lite (Go)](https://github.com/hsanjuan/ipfs-lite/)
- [py-libp2p](https://github.com/libp2p/py-libp2p)
- [Bitswap spec](https://github.com/ipfs/specs/blob/main/BITSWAP.md)
- [py-libp2p issue #2](https://github.com/seetadev/py-libp2p/issues/2)
