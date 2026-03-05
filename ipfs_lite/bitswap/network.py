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
    mh_len, _pos = _decode_varint(digest_bytes, pos)
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
    _mh_len, pos = _decode_varint(prefix, pos)

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
        # Maps CID string -> trio.Event; set when that block arrives via handle_stream
        self._pending_wants: dict[str, trio.Event] = {}
        self._want_queue: list = []
        self._want_ready = trio.Event()

    def add_wants(self, cids: list) -> None:
        """Queue CIDs for the background sender. Register events immediately."""
        for cid in cids:
            cid_str = _cid_key(cid)
            if not self._blockstore.get(cid) and cid_str not in self._pending_wants:
                self._pending_wants[cid_str] = trio.Event()
                self._want_queue.append(cid)
        self._want_ready.set()

    async def wait_for_block(self, cid: CID, timeout: float = 300.0) -> Optional[Block]:
        """Wait for a block whose want was queued via add_wants(). No stream opened."""
        cid_str = _cid_key(cid)
        try:
            block = self._blockstore.get(cid)
            if block:
                return block
            event = self._pending_wants.get(cid_str)
            if event is None:
                logger.warning(f"wait_for_block: no event registered for {cid_str}")
                return self._blockstore.get(cid)
            logger.info(f"wait_for_block: waiting for {cid_str}")
            with trio.move_on_after(timeout) as cs:
                await event.wait()
            if cs.cancelled_caught:
                logger.error(f"wait_for_block: TIMED OUT for {cid_str}")
            else:
                logger.info(f"wait_for_block: event fired for {cid_str}")
            return self._blockstore.get(cid)
        finally:
            self._pending_wants.pop(cid_str, None)

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
                        wl.add_entry(cid, want_type=WantType.Block, send_dont_have=True)
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
            # notify any send_want callers that are waiting.
            for block in msg.payload:
                cid_str = _cid_key(block.cid)
                self._blockstore.put(block)
                event = self._pending_wants.get(cid_str)
                logger.info(f"handle_stream: block {cid_str} event={'found' if event else 'NOT FOUND'}")
                if event is not None:
                    event.set()

            for presence in msg.block_presences:
                logger.info(f"handle_stream: presence cid={presence.cid} type={presence.type}")

            # Handle wantlist requests from remote peer (Python-to-Python or
            # Go peers that use the request-response model on the same stream).
            if msg.wantlist is not None and msg.wantlist.entries:
                response = await self.protocol.handle_message(msg)
                if response is not None:
                    await _write_msg(stream, encode_message(response))
        except Exception as e:
            logger.error(f"Bitswap stream error: {e}", exc_info=True)
        finally:
            await stream.close()

    async def send_want(
        self,
        peer_info: Any,
        cid: CID,
        want_type: WantType = WantType.Block,
        send_dont_have: bool = True,
    ) -> Optional[Message]:
        """Send a wantlist to peer and return a Message with the result.

        Handles two response models:
        1. Same-stream response (Python-to-Python, some Go implementations).
        2. Go's push model: Go opens a new inbound stream to deliver blocks;
           handle_stream stores them and signals the pending event.
        """
        cid_str = _cid_key(cid)
        event = trio.Event()
        self._pending_wants[cid_str] = event

        try:
            stream = await self.host.new_stream(peer_info.peer_id, [self.PROTOCOL_ID])
        except Exception as e:
            logger.error(f"Failed to open stream to {peer_info.peer_id}: {e}")
            self._pending_wants.pop(cid_str, None)
            return None

        try:
            wl = Wantlist()
            wl.add_entry(cid, want_type=want_type, send_dont_have=send_dont_have)
            msg = Message(wantlist=wl)
            await _write_msg(stream, encode_message(msg))

            # --- Try same-stream response (request-response model) ---
            try:
                with trio.move_on_after(2.0):
                    data = await _read_msg(stream)
                    response = decode_message(data)
                    # Store any blocks that arrived on this stream too
                    for block in response.payload:
                        self._blockstore.put(block)
                        ev = self._pending_wants.get(_cid_key(block.cid))
                        if ev is not None:
                            ev.set()
                    if response.payload or response.block_presences:
                        return response
            except Exception:
                pass  # Stream closed or framing error; fall through to push model

            # --- Check if block already arrived via handle_stream ---
            block = self._blockstore.get(cid)
            if block:
                return Message(payload=[block])

            # --- Wait for Go's push model (new inbound stream) ---
            with trio.move_on_after(self._PUSH_TIMEOUT):
                await event.wait()

            block = self._blockstore.get(cid)
            if block:
                return Message(payload=[block])

            logger.error(f"Bitswap send_want error: Block not found for {cid_str}")
            return None
        finally:
            self._pending_wants.pop(cid_str, None)
            await stream.close()

    def get_connected_peers(self) -> List[LP2PPeerInfo]:
        """Return PeerInfo for every peer with an active connection."""
        return [LP2PPeerInfo(pid, []) for pid in self.host.get_connected_peers()]

    async def broadcast_want(
        self,
        peers: List[Any],
        cid: CID,
        want_type: WantType = WantType.Block,
        send_dont_have: bool = True,
    ) -> Optional[Message]:
        """Send a wantlist to all peers concurrently and return the first block received."""
        cid_str = _cid_key(cid)
        event = trio.Event()
        self._pending_wants[cid_str] = event

        try:
            async def try_peer(peer_info, cancel_scope):
                try:
                    stream = await self.host.new_stream(peer_info.peer_id, [self.PROTOCOL_ID])
                except Exception as e:
                    logger.error(f"Failed to open stream to {peer_info.peer_id}: {e}")
                    return
                try:
                    wl = Wantlist()
                    wl.add_entry(cid, want_type=want_type, send_dont_have=send_dont_have)
                    msg_out = Message(wantlist=wl)
                    await _write_msg(stream, encode_message(msg_out))

                    try:
                        with trio.move_on_after(2.0):
                            data = await _read_msg(stream)
                            response = decode_message(data)
                            for block in response.payload:
                                self._blockstore.put(block)
                                ev = self._pending_wants.get(_cid_key(block.cid))
                                if ev is not None:
                                    ev.set()
                            if response.payload or response.block_presences:
                                cancel_scope.cancel()
                                return
                    except Exception:
                        pass
                finally:
                    await stream.close()

            async def wait_for_push(cancel_scope):
                block = self._blockstore.get(cid)
                if block:
                    cancel_scope.cancel()
                    return
                with trio.move_on_after(self._PUSH_TIMEOUT):
                    await event.wait()
                block = self._blockstore.get(cid)
                if block:
                    cancel_scope.cancel()

            with trio.CancelScope() as cancel_scope:
                async with trio.open_nursery() as nursery:
                    for peer_info in peers:
                        nursery.start_soon(try_peer, peer_info, cancel_scope)
                    nursery.start_soon(wait_for_push, cancel_scope)

            block = self._blockstore.get(cid)
            if block:
                return Message(payload=[block])

            logger.error(f"Bitswap broadcast_want: Block not found for {cid_str}")
            return None
        finally:
            self._pending_wants.pop(cid_str, None)
