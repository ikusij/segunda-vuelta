from fetch import fetch
import json
import time

def load_all_ubigeos() -> list[str]:
    with open("hierarchy.json", encoding="utf-8") as f:
        output = json.load(f)
    return list(dict.fromkeys(
        str(dist["ubigeo"])
        for dept in output
        for prov in dept.get("provincias", [])
        for dist in prov.get("distritos", [])
    ))

def fetch_all(
    start: int = 0,
    end: int | None = None,
    max_retries: int = 5,
    bundle_path: str = "bundle.json",
) -> dict:
    all_ubigeos = load_all_ubigeos()
    ubigeos = all_ubigeos[start:end]

    print(f"Fetching {len(ubigeos)} districts (range {start}:{end})...")

    bundle = {}
    failed = list(ubigeos)
    attempt = 0

    while failed and attempt < max_retries:
        attempt += 1
        if attempt > 1:
            print(f"\nRetry {attempt}/{max_retries} — {len(failed)} districts remaining...")
            time.sleep(5)

        next_failed = []
        total = len(failed)

        for pos, ubigeo in enumerate(failed, 1):
            try:
                data = fetch(ubigeo)
                bundle[ubigeo] = data
                print(f"[{pos}/{total}] {ubigeo} OK")
            except Exception as e:
                next_failed.append(ubigeo)
                print(f"[{pos}/{total}] {ubigeo} FAILED: {e}")

        failed = next_failed

    with open(bundle_path, "w", encoding="utf-8") as f:
        json.dump(bundle, f, ensure_ascii=False)

    print(f"\nDone. {len(bundle)} fetched, {len(failed)} still failed after {attempt} attempt(s).")
    if failed:
        print("Still failed:", failed)

    return bundle