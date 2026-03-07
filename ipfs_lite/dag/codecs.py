from enum import Enum


def _read_varint(data: bytes, pos: int) -> tuple[int, int]:
    n, shift = 0, 0
    while True:
        b = data[pos]; pos += 1
        n |= (b & 0x7F) << shift
        if not (b & 0x80):
            break
        shift += 7
    return n, pos


def _skip_field(data: bytes, pos: int, wire_type: int) -> int:
    if wire_type == 0:  # varint
        _, pos = _read_varint(data, pos)
    elif wire_type == 1:  # 64-bit
        pos += 8
    elif wire_type == 2:  # length-delimited
        length, pos = _read_varint(data, pos)
        pos += length
    elif wire_type == 5:  # 32-bit
        pos += 4
    return pos


def decode_dag_pb_all(data: bytes) -> tuple[bytes, list[bytes]]:
    """Extract Data (field 1) and all PBLink.Hash values (field 2.field 1) from a PBNode.

    Returns (unixfs_data_bytes, [cid_bytes, ...]).
    unixfs_data_bytes is b"" if field 1 is absent.
    """
    data_field = b""
    link_cids: list[bytes] = []
    pos = 0
    while pos < len(data):
        tag, pos = _read_varint(data, pos)
        field_number = tag >> 3
        wire_type = tag & 0x07
        if wire_type == 2:
            length, pos = _read_varint(data, pos)
            value = data[pos:pos + length]
            pos += length
            if field_number == 1:  # Data
                data_field = value
            elif field_number == 2:  # PBLink — extract Hash (field 1)
                lpos = 0
                while lpos < len(value):
                    ltag, lpos = _read_varint(value, lpos)
                    lfield = ltag >> 3
                    lwire = ltag & 0x07
                    if lwire == 2:
                        llen, lpos = _read_varint(value, lpos)
                        lval = value[lpos:lpos + llen]
                        lpos += llen
                        if lfield == 1:  # Hash
                            link_cids.append(lval)
                    else:
                        lpos = _skip_field(value, lpos, lwire)
        else:
            pos = _skip_field(data, pos, wire_type)
    return data_field, link_cids


def decode_dag_pb(data: bytes) -> bytes:
    """Extract the Data field (field 1) from a dag-pb PBNode protobuf.

    Returns the embedded UnixFS Data bytes, or b"" if no Data field found.
    """
    data_field, _ = decode_dag_pb_all(data)
    return data_field


def decode_unixfs_data(data: bytes) -> bytes:
    """Extract the Data field (field 2) from a UnixFS Data protobuf.

    Returns the raw file bytes, or b"" if no Data field (multi-block case).
    """
    pos = 0
    while pos < len(data):
        tag, pos = _read_varint(data, pos)
        field_number = tag >> 3
        wire_type = tag & 0x07
        if wire_type == 2:
            length, pos = _read_varint(data, pos)
            value = data[pos:pos + length]
            pos += length
            if field_number == 2:
                return value
        else:
            pos = _skip_field(data, pos, wire_type)
    return b""  # absent = multi-block file; caller must follow links


def _encode_varint(value: int) -> bytes:
    buf = []
    while value > 0x7F:
        buf.append((value & 0x7F) | 0x80)
        value >>= 7
    buf.append(value & 0x7F)
    return bytes(buf)


def _encode_field(field_number: int, wire_type: int, value: bytes) -> bytes:
    tag = _encode_varint((field_number << 3) | wire_type)
    if wire_type == 2:  # length-delimited
        return tag + _encode_varint(len(value)) + value
    if wire_type == 0:  # varint
        return tag + value
    return tag + value


def encode_unixfs_file(data: bytes) -> bytes:
    """Encode data as a UnixFS Data protobuf (type=File).

    UnixFS Data proto:
      field 1 (varint): Type = 2 (File)
      field 2 (bytes):  Data = file content
      field 3 (uint64): filesize
    """
    type_field = _encode_field(1, 0, _encode_varint(2))  # Type.File = 2
    data_field = _encode_field(2, 2, data)
    filesize_field = _encode_field(3, 0, _encode_varint(len(data)))
    return type_field + data_field + filesize_field


def encode_unixfs_internal(filesize: int, blocksizes: list[int]) -> bytes:
    """Encode a UnixFS Data protobuf for an internal (non-leaf) node.

    Internal nodes have type=File, no Data field, filesize = total of children,
    and repeated blocksizes for each child's file size.
    """
    result = _encode_field(1, 0, _encode_varint(2))  # Type.File = 2
    result += _encode_field(3, 0, _encode_varint(filesize))
    for bs in blocksizes:
        result += _encode_field(4, 0, _encode_varint(bs))
    return result


def encode_pb_link(cid_bytes: bytes, tsize: int) -> bytes:
    """Encode a PBLink with Hash and Tsize (no Name for UnixFS)."""
    link = _encode_field(1, 2, cid_bytes)  # Hash
    link += _encode_field(2, 2, b"")       # Name (empty)
    link += _encode_field(3, 0, _encode_varint(tsize))  # Tsize
    return link


def encode_dag_pb(unixfs_data: bytes, links: list[tuple[bytes, int]] | None = None) -> bytes:
    """Encode a PBNode with Data and optional Links.

    dag-pb PBNode proto (canonical order: Links before Data):
      field 2 (repeated): PBLink {Hash, Name, Tsize}
      field 1 (bytes):    Data = serialized UnixFS Data

    links: list of (cid_bytes, tsize) tuples.
    """
    result = b""
    if links:
        for cid_bytes, tsize in links:
            link_bytes = encode_pb_link(cid_bytes, tsize)
            result += _encode_field(2, 2, link_bytes)
    result += _encode_field(1, 2, unixfs_data)
    return result


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
