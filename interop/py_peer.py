#!/usr/bin/env python3
"""
Interop peer: Python IPFS-Lite peer for cross-language testing.

Usage:
  uv run python py_peer.py add --listen /ip4/127.0.0.1/tcp/4011 --data "hello from python"
  uv run python py_peer.py get --connect /ip4/.../p2p/<id> --cid <cid>
"""
import argparse
import hashlib
import io
import logging
import os
import sys

# Configure logging FIRST, before any library imports
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
    stream=sys.stderr,
    force=True,
)
# Suppress noisy loggers
logging.getLogger("multiaddr").setLevel(logging.WARNING)

import trio
from libp2p import new_host
from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.peer.peerinfo import info_from_p2p_addr
from multiaddr import Multiaddr
from multiformats import CID

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))

from ipfs_lite import IPFSLitePeer, MemoryBlockstore
from ipfs_lite.unixfs.file import UnixFSFile


def parse_args():
    parser = argparse.ArgumentParser(description="Python IPFS-Lite interop peer")
    sub = parser.add_subparsers(dest="mode", required=True)

    add_p = sub.add_parser("add", help="Add content and serve it")
    add_p.add_argument("--listen", default="/ip4/127.0.0.1/tcp/4011", help="Listen multiaddr")
    add_p.add_argument("--data", required=True, help="Content to add")

    get_p = sub.add_parser("get", help="Fetch a CID from a peer")
    get_p.add_argument("--listen", default="/ip4/127.0.0.1/tcp/4012", help="Listen multiaddr")
    get_p.add_argument("--connect", required=True, help="Peer multiaddr to connect to")
    get_p.add_argument("--cid", required=True, help="CID to fetch")

    return parser.parse_args()


async def run_add(listen_addr: str, data: str):
    key_pair = create_new_key_pair(hashlib.sha256(b"interop-py-add").digest())
    host = new_host(key_pair=key_pair, muxer_preference="YAMUX")

    async with host.run(listen_addrs=[Multiaddr(listen_addr)]):
        peer = IPFSLitePeer(host, MemoryBlockstore())
        async with trio.open_nursery() as nursery:
            await peer.start(nursery)

            unixfs = UnixFSFile(peer.dag)
            if os.path.isfile(data):
                with open(data, "rb") as f:
                    cid = unixfs.add_file(f)
            else:
                cid = unixfs.add_file(io.BytesIO(data.encode()))

            peer_id = peer.peer_id
            addr = f"{listen_addr}/p2p/{peer_id}"

            print(f"PEER_ID={peer_id}", flush=True)
            print(f"ADDR={addr}", flush=True)
            print(f"CID={cid}", flush=True)
            print("READY", flush=True)

            # Stay running until killed
            await trio.sleep_forever()


async def run_get(listen_addr: str, connect_addr: str, cid_str: str):
    key_pair = create_new_key_pair(hashlib.sha256(b"interop-py-get").digest())
    host = new_host(key_pair=key_pair, muxer_preference="YAMUX")

    async with host.run(listen_addrs=[Multiaddr(listen_addr)]):
        peer = IPFSLitePeer(host, MemoryBlockstore())
        async with trio.open_nursery() as nursery:
            await peer.start(nursery)

            # Connect to remote peer
            ma = Multiaddr(connect_addr)
            peer_info = info_from_p2p_addr(ma)
            await host.connect(peer_info)

            cid = CID.decode(cid_str)
            unixfs = UnixFSFile(peer.dag)
            content = await unixfs.get_file(cid, peers=[peer_info])
            raw = content.read()

            print(f"CONTENT={raw.hex()}", flush=True)

            nursery.cancel_scope.cancel()


def main():
    args = parse_args()
    if args.mode == "add":
        trio.run(run_add, args.listen, args.data)
    else:
        trio.run(run_get, args.listen, args.connect, args.cid)


if __name__ == "__main__":
    main()
