package main

import (
	"context"
	"encoding/hex"
	"flag"
	"fmt"
	"io"
	"os"
	"os/signal"
	"strings"
	"syscall"

	ipfslite "github.com/hsanjuan/ipfs-lite"
	"github.com/ipfs/go-cid"
	"github.com/libp2p/go-libp2p/core/crypto"
	"github.com/libp2p/go-libp2p/core/peer"
	"github.com/multiformats/go-multiaddr"
)

func main() {
	addMode := flag.Bool("add", false, "Add mode: add a file and serve it")
	getMode := flag.Bool("get", false, "Get mode: fetch a CID from a peer")
	listen := flag.String("listen", "/ip4/127.0.0.1/tcp/4010", "Listen multiaddr")
	file := flag.String("file", "", "Content to add (add mode)")
	connect := flag.String("connect", "", "Peer multiaddr to connect to (get mode)")
	cidStr := flag.String("cid", "", "CID to fetch (get mode)")
	flag.Parse()

	if !*addMode && !*getMode {
		fmt.Fprintln(os.Stderr, "Must specify --add or --get")
		os.Exit(1)
	}

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	ds := ipfslite.NewInMemoryDatastore()
	priv, _, err := crypto.GenerateKeyPair(crypto.Ed25519, 0)
	if err != nil {
		fatal("generate key", err)
	}

	listenAddr, err := multiaddr.NewMultiaddr(*listen)
	if err != nil {
		fatal("parse listen addr", err)
	}

	h, dht, err := ipfslite.SetupLibp2p(
		ctx,
		priv,
		nil, // no PSK
		[]multiaddr.Multiaddr{listenAddr},
		ds,
		ipfslite.Libp2pOptionsExtra...,
	)
	if err != nil {
		fatal("setup libp2p", err)
	}

	lite, err := ipfslite.New(ctx, ds, nil, h, dht, nil)
	if err != nil {
		fatal("new peer", err)
	}

	if *addMode {
		runAdd(ctx, lite, h, *file)
	} else {
		runGet(ctx, lite, h, *connect, *cidStr)
	}
}

func runAdd(ctx context.Context, lite *ipfslite.Peer, h interface{ ID() peer.ID; Addrs() []multiaddr.Multiaddr }, content string) {
	if content == "" {
		fmt.Fprintln(os.Stderr, "Must specify --file with content or file path to add")
		os.Exit(1)
	}

	var r io.Reader
	if f, err := os.Open(content); err == nil {
		defer f.Close()
		r = f
		fmt.Fprintf(os.Stderr, "Adding file: %s\n", content)
	} else {
		r = strings.NewReader(content)
	}

	node, err := lite.AddFile(ctx, r, nil)
	if err != nil {
		fatal("add file", err)
	}

	peerID := h.ID()
	addrs := h.Addrs()
	var addrStr string
	for _, a := range addrs {
		s := a.String()
		if strings.Contains(s, "/tcp/") {
			addrStr = fmt.Sprintf("%s/p2p/%s", s, peerID)
			break
		}
	}
	if addrStr == "" && len(addrs) > 0 {
		addrStr = fmt.Sprintf("%s/p2p/%s", addrs[0], peerID)
	}

	fmt.Printf("PEER_ID=%s\n", peerID)
	fmt.Printf("ADDR=%s\n", addrStr)
	fmt.Printf("CID=%s\n", node.Cid())
	fmt.Println("READY")

	// Wait for SIGINT
	sig := make(chan os.Signal, 1)
	signal.Notify(sig, syscall.SIGINT, syscall.SIGTERM)
	<-sig
	fmt.Fprintln(os.Stderr, "Shutting down")
}

func runGet(ctx context.Context, lite *ipfslite.Peer, h interface{ ID() peer.ID; Connect(context.Context, peer.AddrInfo) error }, connectAddr string, cidStr string) {
	if connectAddr == "" || cidStr == "" {
		fmt.Fprintln(os.Stderr, "Must specify --connect and --cid")
		os.Exit(1)
	}

	// Parse and connect to peer
	ma, err := multiaddr.NewMultiaddr(connectAddr)
	if err != nil {
		fatal("parse connect addr", err)
	}
	pinfo, err := peer.AddrInfoFromP2pAddr(ma)
	if err != nil {
		fatal("parse peer info", err)
	}

	fmt.Fprintln(os.Stderr, "Connecting to peer...")
	if err := h.Connect(ctx, *pinfo); err != nil {
		fatal("connect", err)
	}
	fmt.Fprintln(os.Stderr, "Connected.")

	// Bootstrap to the connected peer so bitswap knows about it
	lite.Bootstrap([]peer.AddrInfo{*pinfo})

	c, err := cid.Decode(cidStr)
	if err != nil {
		fatal("decode cid", err)
	}

	fmt.Fprintf(os.Stderr, "Fetching CID %s...\n", c)

	// Try GetFile first (for UnixFS dag-pb nodes from Go)
	rsc, err := lite.GetFile(ctx, c)
	if err == nil {
		data, err := io.ReadAll(rsc)
		rsc.Close()
		if err != nil {
			fatal("read file", err)
		}
		fmt.Printf("CONTENT=%s\n", hex.EncodeToString(data))
		return
	}

	// Fall back to raw Get() for Python's raw blocks
	node, err := lite.Get(ctx, c)
	if err != nil {
		fatal("get block", err)
	}

	fmt.Printf("CONTENT=%s\n", hex.EncodeToString(node.RawData()))
}

func fatal(msg string, err error) {
	fmt.Fprintf(os.Stderr, "ERROR: %s: %v\n", msg, err)
	os.Exit(1)
}
