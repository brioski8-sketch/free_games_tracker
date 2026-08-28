#!/usr/bin/env bash
# End-to-end smoke test for the Jarvis-lite dashboard.
#
# Usage: bash scripts/smoke_test.sh [base_url]
#   base_url defaults to http://localhost:8080
#   Token-protected instances: pass the token via JARVIS_TOKEN env or as 2nd arg.
#
# Validates the graceful-degradation contract (docs/degradation-design.md):
#   - / and static assets serve
#   - /api/status reachable; no widget in 'stale' state (placeholders are fine)
#   - widget endpoints /api/{glucose,resp,news,events} return HTTP 200 (never 502)
#     with parseable JSON containing a state field in {ok, degraded, placeholder};
#     /api/news additionally returns HTTP 200 regardless of feed state
#   - when pointed at an endpoint returning 5xx or an unparseable body, the
#     script prints a clear failure and exits non-zero.
#
# Exit 0 = all checks pass. Non-zero = something is broken; see printed diffs.
set -euo pipefail

BASE="${1:-http://localhost:8080}"
TOKEN="${2:-${JARVIS_TOKEN:-}}"

fail() { echo "FAIL: $*" >&2; exit 1; }

auth=(-H "Authorization: Bearer $TOKEN")
[ -n "$TOKEN" ] || auth=()

echo "== smoke test against $BASE =="

# 1. Static page serves
curl -fsS -o /dev/null "$BASE/" || fail "GET / did not return 200"
echo "ok  GET / (page)"

for asset in app.js style.css vendor/uplot.min.js; do
  curl -fsS -o /dev/null "$BASE/$asset" || fail "GET /$asset did not return 200"
  echo "ok  GET /$asset"
done

# 2. Status endpoint: reachable; no widget in 'stale' state.
#    Per the degradation contract, 'placeholder' widgets are a valid pass
#    against an example-config deployment; only 'stale' is a genuine failure.
status="$(curl -fsS "${auth[@]}" "$BASE/api/status")" || fail "GET /api/status failed"
echo "$status" | python3 -c '
import json, sys
try:
    s = json.load(sys.stdin)
except Exception as e:
    print("/api/status body is not parseable JSON: %s" % e, file=sys.stderr)
    sys.exit(1)
bad = []
for name, w in sorted(s["widgets"].items()):
    desc = "%s: configured=%s state=%s placeholder_reason=%s" % (
        name, w.get("configured"), w.get("state"), w.get("placeholder_reason"))
    if w.get("state") == "stale":
        bad.append(desc)
    else:
        print("ok  status", desc)
if bad:
    print("STALE WIDGETS:", *bad, sep="\n  ", file=sys.stderr)
    sys.exit(1)
' || fail "/api/status reports a stale widget"

# 3. Widget endpoints: HTTP 200 (never 5xx), parseable JSON, valid state field.
for ep in glucose resp news events; do
  # -f makes curl fail on >=400; catch that separately for a clear 5xx message.
  http_code="$(curl -sS -o /tmp/smoke_body.$$ -w '%{http_code}' "${auth[@]}" "$BASE/api/$ep")" \
    || { rm -f /tmp/smoke_body.$$; fail "GET /api/$ep: curl error"; }
  if [ "$http_code" -ge 500 ] 2>/dev/null; then
    rm -f /tmp/smoke_body.$$
    fail "GET /api/$ep returned HTTP $http_code (server error)"
  elif [ "$http_code" -ge 400 ]; then
    rm -f /tmp/smoke_body.$$
    fail "GET /api/$ep returned HTTP $http_code (client error)"
  elif [ "$http_code" != "200" ]; then
    rm -f /tmp/smoke_body.$$
    fail "GET /api/$ep returned unexpected HTTP $http_code"
  fi
  python3 -c '
import json, sys
path, ep = sys.argv[1], sys.argv[2]
try:
    with open(path, "rb") as f:
        d = json.load(f)
except Exception as e:
    print("/api/%s body is not parseable JSON: %s" % (ep, e), file=sys.stderr)
    sys.exit(1)
state = d.get("state")
if state not in ("ok", "degraded", "placeholder"):
    print("/api/%s: state field missing or invalid: %r" % (ep, state), file=sys.stderr)
    sys.exit(1)
if not d.get("fetched_at"):
    print("/api/%s: missing fetched_at" % ep, file=sys.stderr)
    sys.exit(1)
print("ok  GET /api/%s (state=%s)" % (ep, state))
' "/tmp/smoke_body.$$" "$ep" || { rm -f /tmp/smoke_body.$$; fail "/api/$ep payload failed degradation contract"; }
  rm -f /tmp/smoke_body.$$
  echo "ok  GET /api/$ep HTTP 200"
done

echo "ALL CHECKS PASSED"
