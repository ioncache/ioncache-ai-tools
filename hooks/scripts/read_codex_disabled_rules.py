#!/usr/bin/env python3
import json
import sys

def main():
    if len(sys.argv) != 3:
        print("[]")
        return

    config_path, project_root = sys.argv[1], sys.argv[2]
    try:
        import tomllib
        with open(config_path, "rb") as f:
            config = tomllib.load(f)
        project = config.get("projects", {}).get(project_root, {})
        rules = project.get("ioncache-ai-tools", {}).get("disabled_rules", [])
        print(json.dumps(rules))
    except Exception as exc:
        print(f"read_codex_disabled_rules: {exc}", file=sys.stderr)
        print("[]")

if __name__ == "__main__":
    main()
