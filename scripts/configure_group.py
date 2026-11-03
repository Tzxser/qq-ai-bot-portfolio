"""Set the explicitly authorized group in the protected server .env.

This script never prints the group ID or any other configuration value. It is
intended to be invoked by an operator after confirming the target group.
"""
import argparse
import os
from pathlib import Path


def update_env(path, group_id=None, enabled=None, welcome=None):
    if group_id is not None and (not group_id.isdecimal() or int(group_id) <= 0):
        raise ValueError("invalid group id")
    updates = {}
    if group_id is not None:
        updates["ALLOWED_GROUP_IDS"] = group_id
    if enabled is not None:
        updates["GROUP_FEATURES_ENABLED"] = "true" if enabled else "false"
    if welcome is not None:
        updates["WELCOME_ENABLED"] = "true" if welcome else "false"
    lines = path.read_text(encoding="utf-8").splitlines()
    seen = set()
    output = []
    for line in lines:
        key = line.split("=", 1)[0] if "=" in line else ""
        if key in updates:
            output.append(key + "='" + updates[key] + "'")
            seen.add(key)
        else:
            output.append(line)
    for key, value in updates.items():
        if key not in seen:
            output.append(key + "='" + value + "'")
    path.write_text("\n".join(output) + "\n", encoding="utf-8")
    os.chmod(path, 0o600)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", default=".env")
    parser.add_argument("--group-id")
    parser.add_argument("--disable", action="store_true")
    parser.add_argument("--welcome", choices=("on", "off"))
    args = parser.parse_args()
    if not args.disable and not args.group_id:
        parser.error("--group-id is required unless --disable is used")
    update_env(Path(args.env), args.group_id, not args.disable,
               None if args.welcome is None else args.welcome == "on")
    print("GROUP_CONFIG_UPDATED: values withheld")


if __name__ == "__main__":
    main()
