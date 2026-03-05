# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies (uses uv)
uv sync

# Run all tests
uv run pytest

# Run a single test file
uv run pytest tests/integration/test_two_peers.py -v

# Run a single test function
uv run pytest tests/integration/test_two_peers.py::test_block_exchange -v

# Run the litepeer example
uv run python examples/litepeer.py

# Regenerate protobuf bindings (requires grpcio-tools)
uv run python -m grpc_tools.protoc -I. --python_out=. ipfs_lite/bitswap/pb/message.proto
```

## Architecture

The library is a Python port of [ipfs-lite (Go)](https://github.com/hsanjuan/ipfs-lite). It provides an embeddable IPFS peer for IPLD applications.

**Layer stack (top to bottom):**

1. `IPFSLitePeer` (`peer.py`) — entry point; wires all layers together around a py-libp2p `host`
2. `DAGService` (`dag/service.py`) — IPLD DAG operations; delegates to `BlockService`
3. `BlockService` (`block_service.py`) — combines local `Blockstore` with network `Exchange`
4. `BitswapExchange` (`exchange/bitswap.py`) — implements `Exchange` using `BitswapNetwork`
5. `BitswapNetwork` (`bitswap/network.py`) — handles msgio-framed protobuf messages over libp2p streams
6. `BitswapProtocol` (`bitswap/protocol.py`) — pure logic: processes wantlist entries, returns blocks/presences
7. `Blockstore` — `MemoryBlockstore` or `FilesystemBlockstore`

**Key design points:**

- **Runtime**: py-libp2p uses `trio` internally. All integration tests call `trio.run()` directly. Do not mix asyncio and trio in the same execution path — `BlockService` has a fallback for this.
- **Bitswap framing**: Messages are varint-length-prefixed protobuf (go-msgio varint style). See `_read_msg`/`_write_msg` in `network.py`.
- **Block identity**: `Block.from_data()` always creates CIDv1/base32/sha2-256. CID raw bytes (not string) are used as wantlist entry keys in protobuf (`e.block = bytes(entry.cid)`).
- **Protobuf**: Generated file is `ipfs_lite/bitswap/pb/message_pb2.py`; source is `message.proto` in the same directory.
- **Protocol ID**: `/ipfs/bitswap/1.1.0` registered with the libp2p host via `host.set_stream_handler(...)`.

**Go ipfs-lite interop**: Go's bitswap engine does **not** respond on the same stream as the incoming wantlist. It calls `SendMessage` which opens a **new outbound stream** to push blocks back. Python's `handle_stream` must store arriving blocks and signal any pending `send_want` callers.
