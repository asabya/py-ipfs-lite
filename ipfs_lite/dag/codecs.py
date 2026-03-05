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
