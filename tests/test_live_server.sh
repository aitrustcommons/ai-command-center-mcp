#!/bin/bash
# Live server integration tests for AiCC MCP Server
# Usage: AICC_API_KEY=your-key AICC_SERVER_URL=https://mcp.theintentlayer.com ./tests/test_live_server.sh
#
# Requires: curl, python3
# These tests hit the real server with real API calls.

set -euo pipefail

# Configuration from environment
API_KEY="${AICC_API_KEY:?Set AICC_API_KEY environment variable}"
SERVER="${AICC_SERVER_URL:-https://mcp.theintentlayer.com}"
MCP_URL="$SERVER/mcp"

PASSED=0
FAILED=0

# Helper: call an MCP tool and return the data line
call_mcp() {
    local method="$1"
    local params="$2"
    local id="${3:-1}"

    curl -s "$MCP_URL" \
        -H "Authorization: Bearer $API_KEY" \
        -H "Content-Type: application/json" \
        -H "Accept: application/json, text/event-stream" \
        -d "{\"jsonrpc\":\"2.0\",\"id\":$id,\"method\":\"$method\",\"params\":$params}"
}

# Helper: extract JSON from SSE data line
extract_data() {
    grep "^data:" | sed 's/^data: //'
}

# Helper: check if response has error
check_no_error() {
    local test_name="$1"
    local response="$2"

    if echo "$response" | python3 -c "
import json,sys
d = json.load(sys.stdin)
r = d.get('result', {})
if r.get('isError'):
    print('ERROR:', json.loads(r['content'][0]['text']))
    sys.exit(1)
" 2>/dev/null; then
        echo "  PASS: $test_name"
        PASSED=$((PASSED + 1))
    else
        echo "  FAIL: $test_name"
        FAILED=$((FAILED + 1))
    fi
}

echo "=========================================="
echo "AiCC MCP Server -- Live Integration Tests"
echo "Server: $SERVER"
echo "=========================================="
echo ""

# -----------------------------------------------
# Test 1: Health check
# -----------------------------------------------
echo "--- Health Check ---"
HEALTH=$(curl -s "$SERVER/health")
if echo "$HEALTH" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['status']=='healthy'" 2>/dev/null; then
    echo "  PASS: Health check returns healthy"
    PASSED=$((PASSED + 1))
else
    echo "  FAIL: Health check"
    echo "  Response: $HEALTH"
    FAILED=$((FAILED + 1))
fi

# -----------------------------------------------
# Test 2: MCP Initialize
# -----------------------------------------------
echo ""
echo "--- MCP Protocol ---"
INIT=$(call_mcp "initialize" '{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}' 1 | extract_data)
if echo "$INIT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert 'aicc-mcp' in d['result']['serverInfo']['name']" 2>/dev/null; then
    echo "  PASS: MCP initialize handshake"
    PASSED=$((PASSED + 1))
else
    echo "  FAIL: MCP initialize"
    FAILED=$((FAILED + 1))
fi

# -----------------------------------------------
# Test 3: Auth -- invalid key should fail
# -----------------------------------------------
NOAUTH=$(curl -s -o /dev/null -w "%{http_code}" "$MCP_URL" \
    -H "Authorization: Bearer invalid-key" \
    -H "Content-Type: application/json" \
    -H "Accept: application/json, text/event-stream" \
    -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"get_personalities","arguments":{}}}')
if [ "$NOAUTH" = "401" ]; then
    echo "  PASS: Invalid API key returns 401"
    PASSED=$((PASSED + 1))
else
    echo "  FAIL: Invalid API key returned $NOAUTH (expected 401)"
    FAILED=$((FAILED + 1))
fi

# -----------------------------------------------
# Test 4: get_personalities
# -----------------------------------------------
echo ""
echo "--- Identity Tools ---"
PERSONALITIES=$(call_mcp "tools/call" '{"name":"get_personalities","arguments":{}}' 4 | extract_data)
check_no_error "get_personalities" "$PERSONALITIES"

# Check that ops personality exists
if echo "$PERSONALITIES" | python3 -c "
import json,sys
d = json.load(sys.stdin)
text = json.loads(d['result']['content'][0]['text'])
names = [p['name'] for p in text['personalities']]
assert 'ops' in names, f'ops not in {names}'
" 2>/dev/null; then
    echo "  PASS: ops personality found"
    PASSED=$((PASSED + 1))
else
    echo "  FAIL: ops personality not found"
    FAILED=$((FAILED + 1))
fi

# -----------------------------------------------
# Test 5: get_identity_rules
# -----------------------------------------------
RULES=$(call_mcp "tools/call" '{"name":"get_identity_rules","arguments":{}}' 5 | extract_data)
check_no_error "get_identity_rules" "$RULES"

# -----------------------------------------------
# Test 6: get_current_status
# -----------------------------------------------
STATUS=$(call_mcp "tools/call" '{"name":"get_current_status","arguments":{}}' 6 | extract_data)
check_no_error "get_current_status" "$STATUS"

# -----------------------------------------------
# Test 7: detect_mode
# -----------------------------------------------
DETECT=$(call_mcp "tools/call" '{"name":"detect_mode","arguments":{"message":"lets work on the book manuscript"}}' 7 | extract_data)
check_no_error "detect_mode" "$DETECT"

if echo "$DETECT" | python3 -c "
import json,sys
d = json.load(sys.stdin)
text = json.loads(d['result']['content'][0]['text'])
assert text['mode'] == 'book', f'Expected book, got {text[\"mode\"]}'
" 2>/dev/null; then
    echo "  PASS: detect_mode matched 'book'"
    PASSED=$((PASSED + 1))
else
    echo "  FAIL: detect_mode did not match 'book'"
    FAILED=$((FAILED + 1))
fi

# -----------------------------------------------
# Test 8: get_recent_activity
# -----------------------------------------------
ACTIVITY=$(call_mcp "tools/call" '{"name":"get_recent_activity","arguments":{"count":5}}' 8 | extract_data)
check_no_error "get_recent_activity" "$ACTIVITY"

# -----------------------------------------------
# Test 9: list_content
# -----------------------------------------------
echo ""
echo "--- Content Tools ---"
CONTENT=$(call_mcp "tools/call" '{"name":"list_content","arguments":{"path":"identity/personalities"}}' 9 | extract_data)
check_no_error "list_content (identity/personalities)" "$CONTENT"

# -----------------------------------------------
# Test 10: get_document
# -----------------------------------------------
DOC=$(call_mcp "tools/call" '{"name":"get_document","arguments":{"path":"CLAUDE.md"}}' 10 | extract_data)
check_no_error "get_document (CLAUDE.md)" "$DOC"

# -----------------------------------------------
# Test 11: list_work_items
# -----------------------------------------------
echo ""
echo "--- Work Item Tools ---"
ITEMS=$(call_mcp "tools/call" '{"name":"list_work_items","arguments":{}}' 11 | extract_data)
check_no_error "list_work_items" "$ITEMS"

# -----------------------------------------------
# Test 12: get_tracking_areas
# -----------------------------------------------
AREAS=$(call_mcp "tools/call" '{"name":"get_tracking_areas","arguments":{}}' 12 | extract_data)
check_no_error "get_tracking_areas" "$AREAS"

# -----------------------------------------------
# Results
# -----------------------------------------------
echo ""
echo "=========================================="
TOTAL=$((PASSED + FAILED))
echo "Results: $PASSED/$TOTAL passed"
if [ "$FAILED" -gt 0 ]; then
    echo "FAILURES: $FAILED"
    exit 1
else
    echo "All tests passed!"
fi
