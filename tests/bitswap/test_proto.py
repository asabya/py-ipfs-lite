# tests/bitswap/test_proto.py

def test_proto_message_roundtrip():
    """Test protobuf message serializes and deserializes correctly."""
    from ipfs_lite.bitswap.pb import message_pb2 as pb

    msg = pb.Message()
    wl = pb.Message.Wantlist()
    e = pb.Message.Wantlist.Entry()
    e.block = b"\x01\x55\x12\x20" + b"\xab" * 32
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
