from enum import Enum

from ipfs_lite.dag.pb.dag_pb_pb2 import PBLink, PBNode
from ipfs_lite.unixfs.pb.unixfs_pb2 import Data as UnixFSData


def decode_dag_pb_all(data: bytes) -> tuple[bytes, list[bytes]]:
    """Extract Data (field 1) and all PBLink.Hash values (field 2.field 1) from a PBNode.

    Returns (unixfs_data_bytes, [cid_bytes, ...]).
    unixfs_data_bytes is b"" if field 1 is absent.
    """
    node = PBNode()
    node.ParseFromString(data)
    data_field = node.Data if node.HasField("Data") else b""
    link_cids = [link.Hash for link in node.Links]
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
    msg = UnixFSData()
    msg.ParseFromString(data)
    return msg.Data if msg.HasField("Data") else b""


def encode_unixfs_file(data: bytes) -> bytes:
    """Encode data as a UnixFS Data protobuf (type=File)."""
    msg = UnixFSData()
    msg.Type = UnixFSData.File
    msg.Data = data
    msg.filesize = len(data)
    return msg.SerializeToString()


def encode_unixfs_internal(filesize: int, blocksizes: list[int]) -> bytes:
    """Encode a UnixFS Data protobuf for an internal (non-leaf) node.

    Internal nodes have type=File, no Data field, filesize = total of children,
    and repeated blocksizes for each child's file size.
    """
    msg = UnixFSData()
    msg.Type = UnixFSData.File
    msg.filesize = filesize
    for bs in blocksizes:
        msg.blocksizes.append(bs)
    return msg.SerializeToString()


def encode_pb_link(cid_bytes: bytes, tsize: int) -> bytes:
    """Encode a PBLink with Hash and Tsize (no Name for UnixFS)."""
    link = PBLink()
    link.Hash = cid_bytes
    link.Name = ""
    link.Tsize = tsize
    return link.SerializeToString()


def encode_dag_pb(unixfs_data: bytes, links: list[tuple[bytes, int]] | None = None) -> bytes:
    """Encode a PBNode with Data and optional Links.

    DAG-PB canonical order: Links (field 2) serialized before Data (field 1).
    Standard protobuf SerializeToString() emits fields in number order,
    so we manually concatenate to get the correct canonical ordering.
    """
    # Serialize each link as a field 2 length-delimited entry
    result = b""
    if links:
        for cid_bytes, tsize in links:
            link = PBLink()
            link.Hash = cid_bytes
            link.Name = ""
            link.Tsize = tsize
            link_bytes = link.SerializeToString()
            # Field 2, wire type 2 (length-delimited) = (2 << 3) | 2 = 0x12
            result += b"\x12" + _encode_varint(len(link_bytes)) + link_bytes

    # Field 1, wire type 2 (length-delimited) = (1 << 3) | 2 = 0x0a
    result += b"\x0a" + _encode_varint(len(unixfs_data)) + unixfs_data
    return result


def _encode_varint(value: int) -> bytes:
    """Encode an unsigned integer as a protobuf varint."""
    buf = []
    while value > 0x7F:
        buf.append((value & 0x7F) | 0x80)
        value >>= 7
    buf.append(value & 0x7F)
    return bytes(buf)


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
