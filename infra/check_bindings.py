"""Validate rendered Compose configuration, not unexpanded source text."""
import json
import sys

config = json.load(sys.stdin)
for name, service in config["services"].items():
    for port in service.get("ports", []):
        if port.get("host_ip") != "127.0.0.1":
            raise SystemExit(f"non-loopback published port: {name}")
print("All published ports are loopback-only")
