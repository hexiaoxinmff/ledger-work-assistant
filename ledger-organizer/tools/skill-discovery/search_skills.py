"""Read-only generic keyword search of skills.sh; never pass private data."""
import argparse
import json
import sys
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def search(query):
    query = " ".join(query.split())
    if not query or len(query) > 100 or any(ord(c) < 32 for c in query):
        raise ValueError("Use a short generic task query, without private data")
    url = "https://skills.sh/api/search?" + urlencode({"q": query})
    req = Request(url, headers={"User-Agent": "ledger-assistant-skill-discovery/0.15", "Accept": "application/json"})
    with urlopen(req, timeout=12) as response:
        payload = response.read(524289)
    if len(payload) > 524288:
        raise ValueError("Search response exceeds size limit")
    data = json.loads(payload.decode("utf-8"))
    entries = data.get("skills")
    if not isinstance(entries, list):
        raise ValueError("Unexpected search response")
    return [{"name": str(x.get("name", ""))[:160], "id": str(x.get("id", ""))[:250],
             "source": str(x.get("source", ""))[:200], "installs": x.get("installs")}
            for x in entries[:10] if isinstance(x, dict)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", required=True, help="Generic keywords only; sent to skills.sh")
    args = parser.parse_args()
    try:
        print(json.dumps({"source": "skills.sh", "candidates": search(args.query),
                          "notice": "Unverified search results; not installed or executed"}, ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({"error": type(exc).__name__, "message": "Search unavailable; use available platform capabilities"}, ensure_ascii=False), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
