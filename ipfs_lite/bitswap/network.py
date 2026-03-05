# ipfs_lite/bitswap/network.py
import logging
from typing import Any, List, Optional

import trio
from libp2p.peer.peerinfo import PeerInfo as LP2PPeerInfo

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


def _cid_key(cid: CID) -> str:
    """Return a canonical string key for a CID, independent of base encoding.

    CIDv0 → base58btc, CIDv1 → base32. This normalizes e.g. zdj7... and
    bafybei... representations of the same CIDv1 to the same string.
    """
    encoding = "base58btc" if cid.version == 0 else "base32"
    return str(CID(encoding, cid.version, cid.codec.name, cid.digest))


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
    """Encode CID metadata (version, codec, mh func, mh length) as varint-packed bytes.

    The digest stored in CID is raw multihash bytes: [mh_func_code varint][length varint][digest].
    We read the first two varints from the digest bytes to get mh_code and mh_len.
    """
    digest_bytes = cid.digest  # raw multihash bytes
    pos = 0
    mh_code, pos = _decode_varint(digest_bytes, pos)
    mh_len, _ = _decode_varint(digest_bytes, pos)
    return (
        _encode_varint(cid.version)
        + _encode_varint(cid.codec.code)
        + _encode_varint(mh_code)
        + _encode_varint(mh_len)
    )


def _block_from_proto(pb_block) -> Block:
    """Reconstruct a Block from a protobuf Message.Block.

    The prefix encodes [version, codec_code, mh_code, mh_len] as varints.
    We decode the prefix to learn the codec and hash function, then
    rehash the data to reconstruct the CID.
    """
    prefix = bytes(pb_block.prefix)
    data = bytes(pb_block.data)

    pos = 0
    version, pos = _decode_varint(prefix, pos)
    codec_code, pos = _decode_varint(prefix, pos)
    mh_code, pos = _decode_varint(prefix, pos)
    _, pos = _decode_varint(prefix, pos)

    # Look up codec and hash names by their numeric codes
    codec_name = mc._code_table[codec_code].name
    mh_name = mc._code_table[mh_code].name

    digest = multihash.digest(data, mh_name)
    # Use base58btc for CIDv0, base32 for CIDv1
    encoding = "base58btc" if version == 0 else "base32"
    cid = CID(encoding, version, codec_name, digest)
    return Block(cid=cid, data=data)


# --- protobuf encode/decode ---

def encode_message(msg: Message) -> bytes:
    """Encode a Message dataclass to raw protobuf bytes."""
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
    """Decode raw protobuf bytes into a Message dataclass."""
    proto = pb.Message()
    proto.ParseFromString(data)

    wantlist = None
    if proto.HasField("wantlist"):
        entries = []
        for e in proto.wantlist.entries:
            cid = CID.decode(bytes(e.block))
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
        BlockPresence(cid=CID.decode(bytes(bp.cid)), type=BlockPresenceType(bp.type))
        for bp in proto.blockPresences
    ]

    return Message(wantlist=wantlist, payload=payload, block_presences=presences)


# --- msgio framing ---

async def _read_exactly(stream, n: int) -> bytes:
    """Read exactly n bytes from stream, looping as needed."""
    data = b""
    while len(data) < n:
        chunk = await stream.read(n - len(data))
        if not chunk:
            raise EOFError("Stream closed unexpectedly")
        data += chunk
    return data


async def _read_msg(stream) -> bytes:
    """Read a varint-length-prefixed message from stream."""
    length_bytes = b""
    while True:
        chunk = await stream.read(1)
        if not chunk:
            raise EOFError("Stream closed unexpectedly")
        length_bytes += chunk
        if not (chunk[0] & 0x80):
            break
    length, _ = _decode_varint(length_bytes, 0)
    return await _read_exactly(stream, length)


async def _write_msg(stream, data: bytes) -> None:
    """Write a varint-length-prefixed message to stream."""
    await stream.write(_encode_varint(len(data)) + data)


# --- network handler ---

class BitswapNetwork:
    """Handles msgio-framed protobuf Bitswap messages over libp2p streams."""

    PROTOCOL_ID = BITSWAP_PROTOCOL_ID
    # Timeout (seconds) to wait for a block pushed via an inbound stream
    _PUSH_TIMEOUT = 10.0

    def __init__(self, host: Any, protocol: BitswapProtocol):
        self.host = host
        self.protocol = protocol
        self._blockstore = protocol.blockstore
        # Per-CID two-phase state (active fetch via broadcast_want)
        self._have_events: dict[str, trio.Event] = {}   # fired on first HAVE or direct block
        self._have_peers: dict[str, list] = {}          # peer_ids that replied HAVE
        self._block_events: dict[str, trio.Event] = {}  # fired when block stored locally
        # Passive want path (add_wants → _run_sender)
        self._passive_cids: dict[str, CID] = {}         # cid_str → CID for add_wants
        self._want_queue: list = []
        self._want_ready = trio.Event()
        # Server ledger: which peers want which blocks (server role)
        self._peer_wants: dict[str, dict[str, Any]] = {}
        # Outbound delivery queue (blocks/presences → peers, AND want-block requests for passive path)
        self._outbound_queue: list = []
        self._outbound_ready = trio.Event()

    def add_wants(self, cids: list) -> None:
        """Queue CIDs for background want-have sender. Registers passive tracking."""
        for cid in cids:
            cid_str = _cid_key(cid)
            if not self._blockstore.get(cid) and cid_str not in self._passive_cids:
                self._passive_cids[cid_str] = cid
                if cid_str not in self._block_events:
                    self._block_events[cid_str] = trio.Event()
                self._want_queue.append(cid)
        self._want_ready.set()

    async def wait_for_block(self, cid: CID, timeout: float = 300.0) -> Optional[Block]:
        """Wait until the block for cid is stored locally (registered via add_wants)."""
        cid_str = _cid_key(cid)
        block = self._blockstore.get(cid)
        if block:
            return block
        event = self._block_events.get(cid_str)
        if event is None:
            logger.warning(f"wait_for_block: no block_event registered for {cid_str}")
            return self._blockstore.get(cid)
        try:
            with trio.move_on_after(timeout):
                await event.wait()
            return self._blockstore.get(cid)
        finally:
            self._block_events.pop(cid_str, None)
            self._passive_cids.pop(cid_str, None)

    async def _run_sender(self) -> None:
        """Background loop: batch-flush accumulated wants to connected peers."""
        while True:
            await self._want_ready.wait()
            # Brief window to let concurrent _process_block calls pile in
            await trio.sleep(0.002)
            batch = self._want_queue[:]
            self._want_queue.clear()
            self._want_ready = trio.Event()  # reset for next round
            if not batch:
                continue
            peers = self.get_connected_peers()
            if not peers:
                logger.warning("No connected peers, dropping want batch")
                continue
            for peer_info in peers:
                try:
                    stream = await self.host.new_stream(peer_info.peer_id, [self.PROTOCOL_ID])
                    wl = Wantlist()
                    for cid in batch:
                        wl.add_entry(cid, want_type=WantType.Have, send_dont_have=True)
                    await _write_msg(stream, encode_message(Message(wantlist=wl)))
                    await stream.close()
                    logger.info(f"Sent wantlist batch ({len(batch)} CIDs) to {peer_info.peer_id}")
                except Exception as e:
                    logger.error(f"Failed to send batch wantlist to {peer_info.peer_id}: {e}")

    async def handle_stream(self, stream) -> None:
        """Inbound stream handler — registered with libp2p host."""
        try:
            data = await _read_msg(stream)
            msg = decode_message(data)

            logger.info(
                f"handle_stream: blocks={len(msg.payload)}"
                f" presences={len(msg.block_presences)}"
                f" wantlist_entries={len(msg.wantlist.entries) if msg.wantlist else 0}"
            )

            # Go IPFS pushes blocks by opening a new stream; store them and
            # notify any waiters.
            for block in msg.payload:
                cid_str = _cid_key(block.cid)
                self._blockstore.put(block)
                # Fire block_event for active two-phase waiters
                block_event = self._block_events.get(cid_str)
                logger.info(f"handle_stream: block {cid_str} event={'found' if block_event else 'NOT FOUND'}")
                if block_event is not None:
                    block_event.set()
                # Also fire have_event: Go may send the block directly instead of HAVE
                # (WithWantHaveReplaceSize optimization for small blocks)
                have_event = self._have_events.get(cid_str)
                if have_event is not None:
                    have_event.set()

            for presence in msg.block_presences:
                cid_str = _cid_key(presence.cid)
                logger.info(f"handle_stream: presence cid={presence.cid} type={presence.type}")
                if presence.type == BlockPresenceType.Have:
                    peer_id = self._peer_id_from_stream(stream)
                    if cid_str in self._have_peers:
                        # Active two-phase fetch: record HAVE peer and signal waiter
                        if peer_id is not None and peer_id not in self._have_peers[cid_str]:
                            self._have_peers[cid_str].append(peer_id)
                        have_event = self._have_events.get(cid_str)
                        if have_event is not None:
                            have_event.set()
                    elif cid_str in self._passive_cids:
                        # Passive path (add_wants): auto-queue want-block to this peer
                        cid = self._passive_cids[cid_str]
                        wl = Wantlist()
                        wl.add_entry(cid, want_type=WantType.Block, send_dont_have=True)
                        self._queue_outbound(peer_id, Message(wantlist=wl))
                # DONT_HAVE: no action (peer doesn't have it; we move on)

            # Handle wantlist requests from remote peer (Python-to-Python or
            # Go peers that use the request-response model on the same stream).
            if msg.wantlist is not None and msg.wantlist.entries:
                peer_id = self._peer_id_from_stream(stream)
                peer_id_str = str(peer_id)
                response = await self.protocol.handle_message(msg)
                # 2. Update peer ledger + queue outbound response (Go compat)
                # Do this BEFORE the same-stream write so a failed write (e.g.
                # Go already closed its read end) doesn't prevent block delivery.
                if peer_id is not None:
                    self._update_peer_ledger(peer_id_str, peer_id, msg.wantlist)
                    if response is not None:
                        self._queue_outbound(peer_id, response)
                # 1. Same-stream response (Python-to-Python compat only).
                # Go peers close their read end immediately after sending a wantlist,
                # so this write will fail for Go peers. That is expected — blocks are
                # delivered via _run_response_sender (path 2 above) instead.
                if response is not None and (response.payload or response.block_presences):
                    try:
                        await _write_msg(stream, encode_message(response))
                        logger.debug("Same-stream write succeeded (Python-to-Python peer)")
                    except Exception as e:
                        logger.debug(f"Same-stream write failed (Go peer, expected): {e}")
        except Exception as e:
            logger.error(f"Bitswap stream error: {e}", exc_info=True)
        finally:
            await stream.close()

    def _peer_id_from_stream(self, stream) -> Any:
        """Extract the remote PeerID from an inbound stream, or None if unavailable."""
        try:
            return stream.muxed_conn.peer_id
        except AttributeError:
            return None

    def _queue_outbound(self, peer_id: Any, msg: Message) -> None:
        if msg.payload or msg.block_presences:
            self._outbound_queue.append((peer_id, msg))
            self._outbound_ready.set()

    def _update_peer_ledger(self, peer_id_str: str, peer_id: Any, wantlist: Wantlist) -> None:
        """Track unfulfilled wants so notify_new_blocks can push later."""
        if peer_id_str not in self._peer_wants:
            self._peer_wants[peer_id_str] = {"__peer_id__": peer_id}
        wants = self._peer_wants[peer_id_str]
        for entry in wantlist.entries:
            cid_str = _cid_key(entry.cid)
            if entry.cancel:
                wants.pop(cid_str, None)
            elif not self._blockstore.get(entry.cid):
                wants[cid_str] = entry  # block not available yet; remember for later

    def notify_new_blocks(self, blocks: list) -> None:
        """Called when new blocks are stored locally. Push to any peers waiting for them."""
        for block in blocks:
            cid_str = _cid_key(block.cid)
            for _, wants in list(self._peer_wants.items()):
                entry = wants.get(cid_str)
                if entry is None:
                    continue
                peer_id = wants.get("__peer_id__")
                if entry.want_type == WantType.Block:
                    msg = Message(payload=[block])
                else:
                    msg = Message(block_presences=[BlockPresence(cid=block.cid, type=BlockPresenceType.Have)])
                self._queue_outbound(peer_id, msg)
                del wants[cid_str]
            # Also signal any active/passive waiters for this block
            block_event = self._block_events.get(cid_str)
            if block_event is not None:
                block_event.set()
            have_event = self._have_events.get(cid_str)
            if have_event is not None:
                have_event.set()

    # Fallback protocol IDs to try when opening outbound response streams.
    # Go's bitswap accepts both 1.1.0 and 1.2.0; try both in order.
    _RESPONSE_PROTOCOLS = [
        "/ipfs/bitswap/1.2.0",
        "/ipfs/bitswap/1.1.0",
        "/ipfs/bitswap/1.0.0",
    ]

    async def _send_response(self, peer_id: Any, msg: Message) -> None:
        """Open a new outbound stream to peer_id and deliver msg (blocks/presences)."""
        encoded = encode_message(msg)
        for proto in self._RESPONSE_PROTOCOLS:
            try:
                stream = await self.host.new_stream(peer_id, [proto])
                await _write_msg(stream, encoded)
                await stream.close()
                logger.info(
                    f"Sent {len(msg.payload)} blocks, {len(msg.block_presences)}"
                    f" presences to {peer_id} via {proto}"
                )
                return
            except Exception as e:
                logger.debug(f"Failed via {proto} to {peer_id}: {e}")
        logger.error(f"All protocols failed delivering response to {peer_id}")

    async def _run_outbound_sender(self) -> None:
        """Background loop: open new outbound streams to deliver blocks to requesting peers."""
        while True:
            await self._outbound_ready.wait()
            await trio.sleep(0)  # yield so multiple responses can accumulate
            batch = self._outbound_queue[:]
            self._outbound_queue.clear()
            self._outbound_ready = trio.Event()
            async with trio.open_nursery() as nursery:
                for peer_id, msg in batch:
                    nursery.start_soon(self._send_response, peer_id, msg)

    def get_connected_peers(self) -> List[LP2PPeerInfo]:
        """Return PeerInfo for every peer with an active connection."""
        return [LP2PPeerInfo(pid, []) for pid in self.host.get_connected_peers()]

    async def _send_wantlist(self, peer_id: Any, cid: CID, want_type: WantType) -> None:
        """Open a new stream to peer_id, send a single-entry wantlist, close stream."""
        try:
            stream = await self.host.new_stream(peer_id, [self.PROTOCOL_ID])
            wl = Wantlist()
            wl.add_entry(cid, want_type=want_type, send_dont_have=True)
            await _write_msg(stream, encode_message(Message(wantlist=wl)))
            await stream.close()
            logger.debug(f"Sent {want_type.name} for {_cid_key(cid)} to {peer_id}")
        except Exception as e:
            logger.error(f"Failed to send {want_type.name} to {peer_id}: {e}")

    _HAVE_TIMEOUT = 1.5   # seconds to wait for HAVE responses (Phase 1)

    async def broadcast_want(
        self,
        peers: List[Any],
        cid: CID,
    ) -> Optional[Message]:
        """Two-phase block fetch: send want-have to discover peers, then want-block to HAVE peers."""
        cid_str = _cid_key(cid)

        block = self._blockstore.get(cid)
        if block:
            return Message(payload=[block])

        have_event = trio.Event()
        block_event = trio.Event()
        self._have_events[cid_str] = have_event
        self._have_peers[cid_str] = []
        self._block_events[cid_str] = block_event

        try:
            # Phase 1: send want-have to all peers (fire-and-forget)
            async with trio.open_nursery() as nursery:
                for peer_info in peers:
                    nursery.start_soon(self._send_wantlist, peer_info.peer_id, cid, WantType.Have)

            # Wait for first HAVE (or a direct block from Go's small-block shortcut)
            with trio.move_on_after(self._HAVE_TIMEOUT):
                await have_event.wait()

            # Check for direct block arrival (Go sends block instead of HAVE for small blocks)
            block = self._blockstore.get(cid)
            if block:
                return Message(payload=[block])

            have_peers = self._have_peers.get(cid_str, [])
            if not have_peers:
                logger.warning(f"broadcast_want: no peers reported HAVE for {cid_str}")
                return None

            # Phase 2: send want-block to peers that responded with HAVE
            async with trio.open_nursery() as nursery:
                for peer_id in have_peers:
                    nursery.start_soon(self._send_wantlist, peer_id, cid, WantType.Block)

            # Wait for block (peer opens new inbound stream → handle_stream fires block_event)
            with trio.move_on_after(self._PUSH_TIMEOUT):
                await block_event.wait()

            block = self._blockstore.get(cid)
            if block:
                return Message(payload=[block])

            logger.error(f"broadcast_want: block not received after two-phase for {cid_str}")
            return None
        finally:
            self._have_events.pop(cid_str, None)
            self._have_peers.pop(cid_str, None)
            self._block_events.pop(cid_str, None)
