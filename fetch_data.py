import csv
import io
import os
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)


def download(url: str, filename: str) -> str | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            content = resp.read().decode("utf-8-sig", errors="replace")
        path = os.path.join(DATA_DIR, filename)
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(content)
        return content
    except Exception as exc:
        print(f"SKIP {url}: {exc}")
        return None


if __name__ == "__main__":
    col = download("https://www.football-data.co.uk/new/COL.csv", "COL.csv")
    if col:
        rows = list(csv.DictReader(io.StringIO(col)))
        print("COL.csv rows:", len(rows))
        print("COL.csv columns:", list(rows[0].keys()))
        print("COL.csv first:", rows[0].get("Season"), rows[0].get("Date"), rows[0].get("Home"), "vs", rows[0].get("Away"))
        print("COL.csv last:", rows[-1].get("Season"), rows[-1].get("Date"), rows[-1].get("Home"), "vs", rows[-1].get("Away"),
              "PSCH/D/A:", rows[-1].get("PSCH"), rows[-1].get("PSCD"), rows[-1].get("PSCA"),
              "AvgCH/D/A:", rows[-1].get("AvgCH"), rows[-1].get("AvgCD"), rows[-1].get("AvgCA"),
              "B365CH/D/A:", rows[-1].get("B365CH"), rows[-1].get("B365CD"), rows[-1].get("B365CA"))

    # Download European top 5 leagues across recent seasons (22/23 through 26/27)
    leagues = ["E0", "SP1", "I1", "D1", "F1"]
    seasons = ["2223", "2324", "2425", "2526", "2627"]
    for lg in leagues:
        for ss in seasons:
            url = f"https://www.football-data.co.uk/mmz4281/{ss}/{lg}.csv"
            txt = download(url, f"{lg}_{ss}.csv")
            if txt:
                n = len(txt.splitlines()) - 1
                print(f"Downloaded {lg}_{ss}.csv ({n} matches)")
