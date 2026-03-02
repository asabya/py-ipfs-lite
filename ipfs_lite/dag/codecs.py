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
