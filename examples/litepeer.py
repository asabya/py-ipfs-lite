#!/usr/bin/env python3
"""
Litepeer: IPFS-Lite Example

This example starts a single IPFS-Lite peer, connects to bootstrap nodes,
and fetches a file from the IPFS network.

Similar to the Go implementation:
https://github.com/hsanjuan/ipfs-lite/blob/master/examples/litepeer/litepeer.go
"""
import trio
from libp2p import new_host
from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.peer.peerinfo import info_from_p2p_addr
from multiaddr import Multiaddr
from multiformats import CID

from ipfs_lite import IPFSLitePeer, MemoryBlockstore
from ipfs_lite.unixfs.file import UnixFSFile


LISTEN_ADDR = Multiaddr("/ip4/127.0.0.1/tcp/4003")

BOOTSTRAP_ADDRS = [
    "/ip4/104.131.131.82/tcp/4001/p2p/QmaCpDMGvV2BGHeYERUEnRQAwe3N8SzbUtfsmvsqQLuvuJ"
]

TARGET_CID = "QmWATWQ7fVPP2EFGu71UkfnqhYXDYH566qy47CnJDgvs8u"


def make_host(seed: bytes):
    """Create a libp2p host from a deterministic seed."""
    key_pair = create_new_key_pair(seed)
    return new_host(key_pair=key_pair)


async def main():
    host = make_host(b"litepeer" * 4)

    async with host.run(listen_addrs=[LISTEN_ADDR]):
        ipfs_peer = IPFSLitePeer(host, MemoryBlockstore())

        async with trio.open_nursery() as nursery:
            await ipfs_peer.start(nursery)

            print(f"Peer ID: {ipfs_peer.peer_id}")

            connected_peer = None
            for addr_str in BOOTSTRAP_ADDRS:
                try:
                    addr = Multiaddr(addr_str)
                    peer_info = info_from_p2p_addr(addr)
                    await host.connect(peer_info)
                    print(f"Connected to bootstrap: {addr_str}")
                    connected_peer = peer_info
                    break
                except Exception as e:
                    print(f"Failed to connect to {addr_str}: {e}")
                    continue

            if connected_peer is None:
                print("Failed to connect to any bootstrap node")
                nursery.cancel_scope.cancel()
                return

            print(f"Fetching CID: {TARGET_CID}")
            cid = CID.decode(TARGET_CID)
            unixfs = UnixFSFile(ipfs_peer.dag)
            try:
                content = await unixfs.get_file(cid)
                
                print(f"Got {content.read()}")
            except (ValueError, OSError) as e:
                print(f"Failed to retrieve file: {e}")

            nursery.cancel_scope.cancel()

if __name__ == "__main__":
    trio.run(main)
