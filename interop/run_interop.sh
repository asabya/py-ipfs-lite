#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYPROJECT_DIR="$SCRIPT_DIR/.."
cd "$SCRIPT_DIR"

# Cleanup on exit
PIDS=()
cleanup() {
    for pid in "${PIDS[@]+"${PIDS[@]}"}"; do
        kill "$pid" 2>/dev/null || true
        wait "$pid" 2>/dev/null || true
    done
}
trap cleanup EXIT

# Helper: wait for READY line and parse output
wait_ready() {
    local pid=$1
    local outfile=$2
    local timeout=30
    local elapsed=0
    while [ $elapsed -lt $timeout ]; do
        if grep -q "^READY" "$outfile" 2>/dev/null; then
            return 0
        fi
        if ! kill -0 "$pid" 2>/dev/null; then
            echo "ERROR: Process $pid exited before READY"
            cat "$outfile"
            return 1
        fi
        sleep 0.5
        elapsed=$((elapsed + 1))
    done
    echo "ERROR: Timeout waiting for READY"
    cat "$outfile"
    return 1
}

parse_var() {
    grep "^$1=" "$2" | head -1 | cut -d= -f2-
}

echo "=== Building Go peer ==="
cd go_peer
go build -o go_peer .
cd ..

GO_PEER="./go_peer/go_peer"

echo ""
echo "========================================="
echo "  Test 1: Go adds file -> Python fetches"
echo "========================================="

GO_OUT=$(mktemp)
$GO_PEER --add --listen /ip4/127.0.0.1/tcp/4010 --file "hello from go" > "$GO_OUT" 2>/dev/null &
GO_PID=$!
PIDS+=("$GO_PID")

wait_ready "$GO_PID" "$GO_OUT"
GO_ADDR=$(parse_var ADDR "$GO_OUT")
GO_CID=$(parse_var CID "$GO_OUT")
echo "Go peer: ADDR=$GO_ADDR CID=$GO_CID"

PY_OUT=$(mktemp)
(cd "$PYPROJECT_DIR" && uv run python "$SCRIPT_DIR/py_peer.py" get \
    --connect "$GO_ADDR" --cid "$GO_CID" > "$PY_OUT" 2>/dev/null)
PY_CONTENT_HEX=$(parse_var CONTENT "$PY_OUT")

EXPECTED_HEX=$(printf "hello from go" | xxd -p | tr -d '\n')

if [ "$PY_CONTENT_HEX" = "$EXPECTED_HEX" ]; then
    echo "PASS: Python received correct content from Go"
else
    echo "FAIL: Content mismatch"
    echo "  Expected: $EXPECTED_HEX"
    echo "  Got:      $PY_CONTENT_HEX"
    cat "$PY_OUT"
    exit 1
fi

# Kill Go peer
kill "$GO_PID" 2>/dev/null || true
wait "$GO_PID" 2>/dev/null || true
PIDS=()

echo ""
echo "========================================="
echo "  Test 2: Python adds file -> Go fetches"
echo "========================================="

PY_ADD_OUT=$(mktemp)
PY_ADD_ERR=$(mktemp)
(cd "$PYPROJECT_DIR" && uv run python "$SCRIPT_DIR/py_peer.py" add \
    --listen /ip4/127.0.0.1/tcp/4011 --data "hello from python" > "$PY_ADD_OUT" 2>"$PY_ADD_ERR") &
PY_PID=$!
PIDS+=("$PY_PID")

wait_ready "$PY_PID" "$PY_ADD_OUT"
PY_ADDR=$(parse_var ADDR "$PY_ADD_OUT")
PY_CID=$(parse_var CID "$PY_ADD_OUT")
echo "Python peer: ADDR=$PY_ADDR CID=$PY_CID"

GO_GET_OUT=$(mktemp)
GO_GET_ERR=$(mktemp)
timeout 60 $GO_PEER --get --connect "$PY_ADDR" --cid "$PY_CID" > "$GO_GET_OUT" 2>"$GO_GET_ERR" || {
    echo "Go get timed out or failed"
    echo "--- Go stderr ---"
    cat "$GO_GET_ERR"
    exit 1
}
GO_CONTENT_HEX=$(parse_var CONTENT "$GO_GET_OUT")

EXPECTED_HEX=$(printf "hello from python" | xxd -p | tr -d '\n')

if [ "$GO_CONTENT_HEX" = "$EXPECTED_HEX" ]; then
    echo "PASS: Go received correct content from Python"
else
    echo "FAIL: Content mismatch"
    echo "  Expected: $EXPECTED_HEX"
    echo "  Got:      $GO_CONTENT_HEX"
    echo "--- Go stdout ---"
    cat "$GO_GET_OUT"
    echo "--- Go stderr ---"
    cat "$GO_GET_ERR"
    echo "--- Python stderr ---"
    tail -50 "$PY_ADD_ERR"
    exit 1
fi

# Kill Python peer
kill "$PY_PID" 2>/dev/null || true
wait "$PY_PID" 2>/dev/null || true
PIDS=()

# Large file test: use the built go_peer binary itself (absolute path for cd contexts)
LARGE_FILE="$(cd "$(dirname "$GO_PEER")" && pwd)/$(basename "$GO_PEER")"

echo ""
echo "========================================="
echo "  Test 3: Go adds large file -> Python fetches"
echo "========================================="

GO_OUT3=$(mktemp)
GO_ERR3=$(mktemp)
$GO_PEER --add --listen /ip4/127.0.0.1/tcp/4020 --file "$LARGE_FILE" > "$GO_OUT3" 2>"$GO_ERR3" &
GO_PID3=$!
PIDS+=("$GO_PID3")

wait_ready "$GO_PID3" "$GO_OUT3"
GO_ADDR3=$(parse_var ADDR "$GO_OUT3")
GO_CID3=$(parse_var CID "$GO_OUT3")
echo "Go peer: CID=$GO_CID3"

PY_OUT3=$(mktemp)
PY_ERR3=$(mktemp)
timeout 300 bash -c "cd \"$PYPROJECT_DIR\" && uv run python \"$SCRIPT_DIR/py_peer.py\" get \
    --connect \"$GO_ADDR3\" --cid \"$GO_CID3\" > \"$PY_OUT3\" 2>\"$PY_ERR3\"" || {
    echo "Python get timed out or failed"
    echo "--- Python stderr ---"
    tail -30 "$PY_ERR3"
    exit 1
}
PY_CONTENT_HEX3=$(parse_var CONTENT "$PY_OUT3")
EXPECTED_HEX3=$(xxd -p "$LARGE_FILE" | tr -d '\n')

if [ "$PY_CONTENT_HEX3" = "$EXPECTED_HEX3" ]; then
    echo "PASS: Python received correct large file from Go"
else
    echo "FAIL: Content mismatch (large file)"
    echo "  Expected length: ${#EXPECTED_HEX3}"
    echo "  Got length:      ${#PY_CONTENT_HEX3}"
    exit 1
fi

kill "$GO_PID3" 2>/dev/null || true
wait "$GO_PID3" 2>/dev/null || true
PIDS=()

echo ""
echo "========================================="
echo "  Test 4: Python adds large file -> Go fetches"
echo "========================================="

PY_ADD_OUT4=$(mktemp)
PY_ADD_ERR4=$(mktemp)
(cd "$PYPROJECT_DIR" && uv run python "$SCRIPT_DIR/py_peer.py" add \
    --listen /ip4/127.0.0.1/tcp/4021 --data "$LARGE_FILE" > "$PY_ADD_OUT4" 2>"$PY_ADD_ERR4") &
PY_PID4=$!
PIDS+=("$PY_PID4")

wait_ready "$PY_PID4" "$PY_ADD_OUT4"
PY_ADDR4=$(parse_var ADDR "$PY_ADD_OUT4")
PY_CID4=$(parse_var CID "$PY_ADD_OUT4")
echo "Python peer: CID=$PY_CID4"

# CIDs should match since both use the same UnixFS encoding
if [ "$PY_CID4" = "$GO_CID3" ]; then
    echo "CID match: Go and Python produce same CID for large file"
else
    echo "WARNING: CID mismatch (Go=$GO_CID3 Python=$PY_CID4)"
fi

GO_GET_OUT4=$(mktemp)
GO_GET_ERR4=$(mktemp)
timeout 300 $GO_PEER --get --connect "$PY_ADDR4" --cid "$PY_CID4" > "$GO_GET_OUT4" 2>"$GO_GET_ERR4" || {
    echo "Go get timed out or failed"
    echo "--- Go stderr ---"
    cat "$GO_GET_ERR4"
    echo "--- Python stderr ---"
    tail -30 "$PY_ADD_ERR4"
    exit 1
}
GO_CONTENT_HEX4=$(parse_var CONTENT "$GO_GET_OUT4")

if [ "$GO_CONTENT_HEX4" = "$EXPECTED_HEX3" ]; then
    echo "PASS: Go received correct large file from Python"
else
    echo "FAIL: Content mismatch (large file)"
    echo "  Expected length: ${#EXPECTED_HEX3}"
    echo "  Got length:      ${#GO_CONTENT_HEX4}"
    exit 1
fi

kill "$PY_PID4" 2>/dev/null || true
wait "$PY_PID4" 2>/dev/null || true
PIDS=()

echo ""
echo "========================================="
echo "  All tests passed!"
echo "========================================="
