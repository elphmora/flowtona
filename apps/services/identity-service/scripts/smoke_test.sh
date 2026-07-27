#!/usr/bin/env bash
#
# scripts/smoke_test.sh — End-to-end smoke test against a running
# identity-service. Not a substitute for pytest, which tests
# in-process; this hits real HTTP, the way an operator or CI would.
#
# Portable — uses curl's own request timer (%{time_total}) rather than
# GNU date's nanosecond extension, so this runs identically on Linux
# and macOS with no extra dependencies (no GNU coreutils needed).
#
# Usage:
#   ./scripts/smoke_test.sh
#   BASE_URL=https://identity.flowtona.internal ./scripts/smoke_test.sh
#
# Exits 0 only if every check passed. Never stops at the first
# failure — collects everything so one run shows the full picture.

BASE_URL="${BASE_URL:-http://localhost:8000}"
PASS_COUNT=0
FAIL_COUNT=0
LAST_BODY=""
LAST_STATUS=""
LAST_DURATION=""

for cmd in curl jq; do
    command -v "$cmd" >/dev/null 2>&1 || { echo "ERROR: $cmd not found" >&2; exit 2; }
done

TEMP_DIR=$(mktemp -d)
trap 'rm -rf "$TEMP_DIR"' EXIT

# Status messages go to stderr so command substitution captures only
# the HTTP response body where that's used.
pass() { PASS_COUNT=$((PASS_COUNT + 1)); echo "  PASS: $1" >&2; }
fail() { FAIL_COUNT=$((FAIL_COUNT + 1)); echo "  FAIL: $1" >&2; }

# require_json JQ_FILTER — true if LAST_BODY matches, false otherwise.
require_json() { echo "$LAST_BODY" | jq -e "$1" >/dev/null 2>&1; }

# require_text PATTERN — true if LAST_BODY matches PATTERN.
require_text() { grep -q "$1" <<<"$LAST_BODY"; }

perform_request() {
    local method="$1" path="$2" body="$3"
    if [ -n "$body" ]; then
        curl --silent --show-error --connect-timeout 5 --max-time 15 \
            --write-out $'\n%{http_code}\n%{time_total}' \
            --request "$method" "${BASE_URL}${path}" \
            --header "Content-Type: application/json" --data "$body"
    else
        curl --silent --show-error --connect-timeout 5 --max-time 15 \
            --write-out $'\n%{http_code}\n%{time_total}' \
            --request "$method" "${BASE_URL}${path}"
    fi
}

# check_status NAME METHOD PATH [BODY] EXPECTED_STATUS
#
# Deliberately called as a PLAIN statement, never via $(check_status ...)
# — command substitution runs in a subshell, and PASS_COUNT/FAIL_COUNT
# updates made inside pass()/fail() during that call would be silently
# lost when the subshell exits, even though the stderr messages would
# still print — a script that LOOKS correct while the exit code lies.
# Results go into LAST_BODY/LAST_STATUS/LAST_DURATION instead, read
# by the caller immediately after this returns.
check_status() {
    local name="$1" method="$2" path="$3" body="$4" expected="$5"
    local response without_time

    if ! response=$(perform_request "$method" "$path" "$body"); then
        LAST_BODY=""
        LAST_STATUS=""
        LAST_DURATION=""
        fail "$name — could not connect to ${BASE_URL}${path}"
        return 0
    fi

    # perform_request's --write-out appends two lines after the body:
    # HTTP status, then curl's time_total. Two sed '$d' calls strip
    # them off one at a time (last-to-first) to recover the body alone
    # — this only works because perform_request's format is fixed and
    # controlled entirely here; it's not a general-purpose parser.
    LAST_DURATION=$(printf '%s\n' "$response" | tail -n 1)
    without_time=$(printf '%s\n' "$response" | sed '$d')
    LAST_STATUS=$(printf '%s\n' "$without_time" | tail -n 1)
    LAST_BODY=$(printf '%s\n' "$without_time" | sed '$d')

    if [ "$LAST_STATUS" = "$expected" ]; then
        pass "$name ($LAST_STATUS, ${LAST_DURATION}s)"
    else
        fail "$name (expected $expected, got $LAST_STATUS, ${LAST_DURATION}s) — body: $LAST_BODY"
    fi
}

echo "=== Smoke testing identity-service at ${BASE_URL} ===" >&2

echo "--- Operational surface ---" >&2
check_status "GET /healthz"  GET "/healthz"  "" 200
check_status "GET /readyz"   GET "/readyz"   "" 200
check_status "GET /startupz" GET "/startupz" "" 200
check_status "GET /info"     GET "/info"     "" 200

check_status "GET /.well-known/jwks.json" GET "/.well-known/jwks.json" "" 200
if require_json '.keys | length > 0'; then
    pass "JWKS response contains at least one key"
else
    fail "JWKS response missing a non-empty 'keys' array"
fi

check_status "GET /metrics" GET "/metrics" "" 200
if require_text '^[[:space:]]*http_requests_total'; then
    pass "Metrics output contains http_requests_total"
else
    fail "Metrics output missing http_requests_total"
fi

echo "--- Business flow (signup -> logout -> login -> refresh -> logout) ---" >&2
UNIQUE_EMAIL="smoketest+$(date +%s)-$$-${RANDOM}@example.com"
SIGNUP_BODY=$(printf '{"email":"%s","password":"hunter22","display_name":"Smoke Test","tenant_label":"Smoke Test Co"}' "$UNIQUE_EMAIL")

check_status "POST /v1/auth/signup" POST "/v1/auth/signup" "$SIGNUP_BODY" 201
if require_json '.access_token and .refresh_token'; then
    pass "Signup response contains access_token and refresh_token"
else
    fail "Signup response missing access_token or refresh_token"
fi
SIGNUP_REFRESH_TOKEN=$(echo "$LAST_BODY" | jq -r '.refresh_token // empty')

if [ -n "$SIGNUP_REFRESH_TOKEN" ]; then
    SIGNUP_LOGOUT_BODY=$(printf '{"refresh_token":"%s"}' "$SIGNUP_REFRESH_TOKEN")
    check_status "POST /v1/auth/logout (signup session)" POST "/v1/auth/logout" "$SIGNUP_LOGOUT_BODY" 204
else
    fail "No refresh_token from signup — cannot clean up signup session"
fi

LOGIN_BODY=$(printf '{"email":"%s","password":"hunter22"}' "$UNIQUE_EMAIL")
check_status "POST /v1/auth/login" POST "/v1/auth/login" "$LOGIN_BODY" 200
LOGIN_REFRESH_TOKEN=$(echo "$LAST_BODY" | jq -r '.refresh_token // empty')

if [ -n "$LOGIN_REFRESH_TOKEN" ]; then
    REFRESH_BODY=$(printf '{"refresh_token":"%s"}' "$LOGIN_REFRESH_TOKEN")
    check_status "POST /v1/auth/refresh" POST "/v1/auth/refresh" "$REFRESH_BODY" 200
    ROTATED_TOKEN=$(echo "$LAST_BODY" | jq -r '.refresh_token // empty')

    if [ -n "$ROTATED_TOKEN" ]; then
        FINAL_LOGOUT_BODY=$(printf '{"refresh_token":"%s"}' "$ROTATED_TOKEN")
        check_status "POST /v1/auth/logout (rotated session)" POST "/v1/auth/logout" "$FINAL_LOGOUT_BODY" 204
    else
        fail "Refresh response missing refresh_token — cannot test logout"
    fi
else
    fail "No refresh_token from login — cannot test refresh/logout"
fi

echo "--- Error handling (RFC 9457 + request correlation) ---" >&2
if ! protected_status=$(curl --silent --show-error --connect-timeout 5 --max-time 15 \
    --output "$TEMP_DIR/body.json" --dump-header "$TEMP_DIR/headers.txt" \
    --write-out '%{http_code}' --request POST "${BASE_URL}/v1/auth/logout-all-for-tenant"); then
    fail "Protected-route request could not connect to ${BASE_URL}"
else
    if [ "$protected_status" = "401" ]; then
        pass "Protected route without auth returns 401"
    else
        fail "Protected route without auth expected 401, got $protected_status"
    fi

    if grep -qi "^content-type: application/problem+json" "$TEMP_DIR/headers.txt"; then
        pass "Error response uses application/problem+json"
    else
        fail "Error response does not use application/problem+json"
    fi

    if grep -qi "^x-request-id:" "$TEMP_DIR/headers.txt"; then
        pass "Error response includes X-Request-ID header"
    else
        fail "Error response missing X-Request-ID header"
    fi

    # Only the RFC 9457 spec-core fields — not custom extension fields
    # like code/request_id, which are more likely to drift over time.
    if jq -e '.type and .title and .status == 401 and .detail' "$TEMP_DIR/body.json" >/dev/null 2>&1; then
        pass "Error body contains the RFC 9457 core fields"
    else
        fail "Error body missing expected RFC 9457 fields"
    fi
fi

echo "=== Summary: ${PASS_COUNT} passed, ${FAIL_COUNT} failed ===" >&2
[ "$FAIL_COUNT" -gt 0 ] && exit 1
exit 0