# ipfs_lite/bitswap/network.py
import logging
import struct
from typing import Any, Optional

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
    cid = CID("base32", version, codec_name, digest)
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
    """Read a 4-byte big-endian length-prefixed message from stream."""
    length_bytes = await _read_exactly(stream, 4)
    length = struct.unpack(">I", length_bytes)[0]
    return await _read_exactly(stream, length)


async def _write_msg(stream, data: bytes) -> None:
    """Write a 4-byte big-endian length-prefixed message to stream."""
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
