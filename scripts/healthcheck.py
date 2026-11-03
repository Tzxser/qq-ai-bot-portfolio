import argparse
import json
import urllib.error
import urllib.request


def check(infrastructure=False):
    path = "healthz" if infrastructure else "readyz"
    try:
        with urllib.request.urlopen("http://127.0.0.1:8080/" + path, timeout=7) as response:
            data = json.load(response)
        print(json.dumps(data, sort_keys=True))
        return 0
    except urllib.error.HTTPError as exc:
        print(json.dumps(json.load(exc), sort_keys=True))
        return 2
    except Exception:
        print('{"healthy": false, "reason": "health_endpoint_unreachable"}')
        return 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--infrastructure", action="store_true")
    raise SystemExit(check(parser.parse_args().infrastructure))
