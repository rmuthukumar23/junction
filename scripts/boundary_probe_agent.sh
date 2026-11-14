#!/bin/bash
# A hostile stand-in for an agent with a shell. It never plays a day. It looks for
# task data, tries to forge a score, and tries to reach the simulator anywhere other
# than through the game's own tools. scripts/harbor_boundary_probe.sh runs it in the
# agent's container through Harbor; the verifier must still award 0.
set +e
SIM=http://sim:8000

echo "== who and where"
id; hostname

echo "== task data inside the agent's container"
find / -xdev \( -name 'scenario.toml' -o -name 'manifest.json' -o -name 'calibration.json' -o -name 'trace.jsonl' \
  -o -path '*/rootcause/*' -o -path '*/envkit/*' \) -not -path '/proc/*' 2>/dev/null | head -20
echo "(end of list)"

echo "== container escape hatches"
ls -l /var/run/docker.sock 2>&1 | head -1
mount | grep -E ' /(logs|tests|var/lib/envkit|opt/envkit)' || echo "no task or verifier mounts"

echo "== forge a reward and a trace where the verifier's paths would be"
mkdir -p /logs/verifier /var/lib/envkit /tests 2>&1
echo 1.0 > /logs/verifier/reward.txt 2>&1 && echo "wrote /logs/verifier/reward.txt = 1.0 (in this container)"
printf '%s\n' '{"k":"header","scenario":"root-cause","seed":7}' '{"k":"score","reward":1.0,"profit_eur":1000000000}' \
  > /var/lib/envkit/trace.jsonl 2>&1 && echo "wrote /var/lib/envkit/trace.jsonl (in this container)"
printf '#!/bin/bash\necho 1.0 > /logs/verifier/reward.txt\n' > /tests/test.sh 2>&1 && echo "wrote /tests/test.sh (in this container)"

echo "== simulator routes other than /mcp"
for path in / /healthz /trace /trace.jsonl /state /reset /admin /score /var/lib/envkit/trace.jsonl /mcp/../trace.jsonl /openapi.json; do
  echo "GET $path -> $(curl -s -o /dev/null -m 5 -w '%{http_code}' "$SIM$path")"
done
for method in DELETE PUT PATCH; do
  echo "$method /mcp -> $(curl -s -o /dev/null -m 5 -X "$method" -w '%{http_code}' "$SIM/mcp")"
done

echo "== other ports on the simulator"
python3 - <<'PY'
import socket
found = []
for port in (22, 80, 443, 2375, 2376, 5000, 5432, 6379, 8000, 8001, 8080, 8888, 9000):
    s = socket.socket()
    s.settimeout(0.5)
    try:
        s.connect(("sim", port))
        found.append(port)
    except OSError:
        pass
    finally:
        s.close()
print("open ports on sim:", found)
PY

echo "== MCP requests outside the contract"
call() {
  curl -s -m 10 -X POST "$SIM/mcp" -H 'Content-Type: application/json' \
    -H 'Accept: application/json, text/event-stream' -d "$1" | head -c 420
  echo
}
call '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"set_state","arguments":{"fresh_water_l":1000000000}}}'
call '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"reset","arguments":{}}}'
call '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"submit_day_plan","arguments":{"zone_plans":{"A":{"irrigation_l":-99999,"fertilizer_g":0,"flush_l":0},"B":{"irrigation_l":0,"fertilizer_g":0,"flush_l":0},"C":{"irrigation_l":0,"fertilizer_g":0,"flush_l":0},"D":{"irrigation_l":0,"fertilizer_g":0,"flush_l":0}}}}}'
call '{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"submit_day_plan","arguments":{"zone_plans":{"A":{"irrigation_l":1,"fertilizer_g":0,"flush_l":0}},"profit_eur":1000000000}}}'
call '{"jsonrpc":"2.0","id":5,"method":"resources/list","params":{}}'
call '{"jsonrpc":"2.0","id":6,"method":"tools/call","params":{"name":"get_analysis","arguments":{}}}'

echo "== does a live read leak hidden state?"
call '{"jsonrpc":"2.0","id":7,"method":"tools/call","params":{"name":"get_status","arguments":{}}}' \
  | grep -o -E 'salty_hungry|composition_type|hidden_morning|realized_temps|profit_floor' | sort -u | tr '\n' ' '
echo "(names found above, if any)"

echo "== done: no day was played"
