"""vatscope's data: VATSIM's pilots, controllers, ATIS and flight plans, from the public VATSIM data feed (no key).

VATSIM's feed rules (https://vatsim.dev/services/apis): find the feed's URLs through status.json, and don't
fetch the feed more often than it updates (every 15 s). Here the feed is fetched only when a page asks for it,
at most once per 15 s for everyone, and the controllers' positions (transceivers feed) at most once a minute.
"""
import calendar
import gzip
import json
import random
import re
import threading
import time
import urllib.request

from scope.core import gc_nm
from scope.weather import Atis

STATUS = "https://status.vatsim.net/status.json"
FEED = "https://data.vatsim.net/v3/vatsim-data.json"
TRANSCEIVERS = "https://data.vatsim.net/v3/transceivers-data.json"
UA = {"User-Agent": "vatscope/1 (+https://github.com/kyleboas/vatscope)", "Accept": "application/json",
      "Accept-Encoding": "gzip"}
FAC = {1: "Center", 2: "Clearance", 3: "Ground", 4: "Tower", 5: "Approach", 6: "Center"}   # FSS shows as Center
CALL = re.compile(r"[A-Z0-9_-]{2,20}")


def fetch(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20) as r:
        body = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            body = gzip.decompress(body)
    return json.loads(body)


def parse_t(s):
    """'2026-11-14T17:23:42.7819399Z' -> unix seconds"""
    try:
        return calendar.timegm(time.strptime((s or "")[:19], "%Y-%m-%dT%H:%M:%S"))
    except ValueError:
        return 0.0


class Cached:
    """one value, fetched when asked for and at least `every` seconds old"""

    def __init__(self, every, load):
        self.every, self.load = every, load
        self.v, self.t, self.err, self.tried = None, 0.0, "", 0.0
        self.lock = threading.Lock()

    def get(self):
        with self.lock:
            now = time.time()
            if now - self.t >= self.every and now - self.tried >= 10:
                self.tried = now
                try:
                    self.v, self.t, self.err = self.load(), now, ""
                except Exception as e:  # noqa: BLE001 - feed down: keep the last one
                    self.err = type(e).__name__
            return self.v, self.t, self.err


class Live:
    def __init__(self, airports):
        self.airports = airports
        self.iata = {}
        for a in airports.all:
            if a[1] and a[8] in "LMS":
                self.iata.setdefault(a[1].upper(), a)
        self.urls = Cached(3600, self.load_urls)
        self.feed = Cached(15, self.load_feed)
        self.tx = Cached(60, lambda: {x["callsign"]: x.get("transceivers") or [] for x in fetch(self.url("transceivers", TRANSCEIVERS))})
        self.prev = {}             # cid -> (time, altitude), for vertical speed between feed updates

    def load_urls(self):
        return fetch(STATUS).get("data") or {}

    def url(self, kind, default):
        u, _, _ = self.urls.get()
        opts = (u or {}).get(kind) or []
        return random.choice(opts) if opts else default

    # ---------------------------------------------------------------- airports
    def airport(self, prefix):
        """a callsign's first part (KSFO, SFO, EGLL) -> the airport row, or None"""
        p = prefix.upper()
        return (self.airports.by_id.get(p) or (len(p) == 3 and (self.airports.by_id.get("K" + p) or self.iata.get(p)))
                or None)

    def near_airport(self, lat, lon, nm=60):
        best, bd = None, nm
        for a in self.airports.major:
            if abs(a[5] - lat) > 1.2:
                continue
            d = gc_nm(lat, lon, a[5], a[6])
            if d < bd:
                best, bd = a, d
        return best

    def ap_pos(self, icao):
        a = self.airports.by_id.get((icao or "").upper())
        return (a[5], a[6]) if a else (None, None)

    # ---------------------------------------------------------------- pilots
    def load_feed(self):
        d = fetch(self.url("v3", FEED))
        now = time.time()
        pilots, prev = [], {}
        for p in d.get("pilots") or []:
            lat, lon = p.get("latitude"), p.get("longitude")
            if lat is None or lon is None:
                continue
            fp = p.get("flight_plan") or {}
            ts = parse_t(p.get("last_updated")) or now
            alt, gs = int(p.get("altitude") or 0), int(p.get("groundspeed") or 0)
            cid = str(p.get("cid") or p.get("callsign"))
            vs, old = 0, self.prev.get(cid)
            if old and ts - old[0] >= 5:
                vs = int(round((alt - old[1]) / (ts - old[0]) * 60 / 50) * 50)
                vs = vs if abs(vs) < 8000 else 0
            prev[cid] = (ts, alt) if not old or ts - old[0] >= 5 else old
            ground = gs < 45 and abs(vs) < 300
            dep, arr = (fp.get("departure") or "").upper(), (fp.get("arrival") or "").upper()
            route = None
            if dep or arr:
                route = [dep, *self.ap_pos(dep), arr, *self.ap_pos(arr)]
            typ = (fp.get("aircraft_short") or "").upper()
            pilots.append({"id": cid, "cs": (p.get("callsign") or "").strip() or "----", "lat": round(lat, 5), "lon": round(lon, 5),
                           "alt": alt, "gs": gs, "hdg": p.get("heading") or 0, "vs": vs, "ts": ts, "ground": ground, "air": not ground,
                           "type": typ, "acName": fp.get("aircraft_faa") or typ, "livery": "", "user": p.get("name") or "",
                           "vo": f"CID {p.get('cid')}" if p.get("cid") else "", "away": False, "route": route,
                           "reg": "", "sq": p.get("transponder") or "", "emer": "", "hex": "", "cat": "",
                           "fp": {"rules": fp.get("flight_rules") or "", "route": fp.get("route") or "", "alt": fp.get("altitude") or "",
                                  "remarks": fp.get("remarks") or ""} if fp else None})
        self.prev = prev
        return {"pilots": pilots, "by_id": {p["id"]: p for p in pilots}, "controllers": d.get("controllers") or [],
                "atis": d.get("atis") or [], "users": (d.get("general") or {}).get("unique_users") or 0}

    def area(self, lat, lon, nm):
        v, t, err = self.feed.get()
        dlat = nm / 60 + 0.1
        out = []
        for a in (v or {}).get("pilots", []):
            if abs(a["lat"] - lat) > dlat:
                continue
            d = gc_nm(lat, lon, a["lat"], a["lon"])
            if d <= nm:
                out.append({**{k: x for k, x in a.items() if k != "fp"}, "dist": round(d, 1)})
        return {"ok": bool(t), "err": err, "t": t, "src": "VATSIM", "center": [round(lat, 3), round(lon, 3)], "nm": round(nm), "aircraft": out}

    def everywhere(self):
        v, t, _ = self.feed.get()
        ac = [[a["id"], a["lat"], a["lon"], round(a["hdg"]), a["gs"], round(a["alt"] / 100), int(a["ts"]), a["cs"], 1 if a["ground"] else 0]
              for a in (v or {}).get("pilots", [])]
        return {"ok": bool(t), "t": t, "every": 15, "src": "VATSIM", "ac": ac, "est": []}

    def flight(self, fid):
        v, _, _ = self.feed.get()
        a = (v or {}).get("by_id", {}).get(fid)
        if not a:
            return {"ok": False}
        fp, r = a.get("fp") or {}, a.get("route")
        pts = [p for p in ([r[0], r[1], r[2], "", ""], [r[3], r[4], r[5], "", ""]) if p[1] is not None] if r else []
        return {"ok": True, "plan": {"ifr": fp.get("rules") == "I", "pts": pts if len(pts) == 2 else [],
                                     "text": " ".join(x for x in (r and r[0], fp.get("route"), r and r[3]) if x),
                                     "alt": fp.get("alt") or ""}, "planErr": "" if fp else "no flight plan filed"}

    # ---------------------------------------------------------------- ATC and ATIS
    def atc(self):
        v, t, err = self.feed.get()
        if not v:
            return {"ok": False, "err": err, "atc": []}
        tx, _, _ = self.tx.get()
        out = []
        for c in v["controllers"]:
            typ = FAC.get(c.get("facility"))
            cs = (c.get("callsign") or "").upper()
            if not typ or not CALL.fullmatch(cs) or (c.get("frequency") or "").startswith("199.998"):
                continue                                   # observers and controllers not on a frequency
            if typ == "Approach" and cs.endswith("_DEP"):
                typ = "Departure"
            parts = cs.split("_")
            ap = self.airport(parts[0])
            ts = (tx or {}).get(c.get("callsign")) or []
            lat = sum(x["latDeg"] for x in ts) / len(ts) if ts else (ap[5] if ap else None)
            lon = sum(x["lonDeg"] for x in ts) / len(ts) if ts else (ap[6] if ap else None)
            if typ != "Center" and not ap and lat is not None:
                ap = self.near_airport(lat, lon)          # NCT_APP, SCT_APP...: the airport nearest its antenna
            if typ != "Center" and not ap:
                continue
            out.append({"icao": ap[0] if ap and typ != "Center" else parts[0], "type": typ,
                        "user": f"{cs} {c.get('frequency') or ''}".strip(), "name": c.get("name") or "",
                        "lat": lat, "lon": lon, "since": parse_t(c.get("logon_time"))})
        for a in v["atis"]:
            cs = (a.get("callsign") or "").upper()
            ap = self.airport(cs.split("_")[0])
            if ap and not (a.get("frequency") or "").startswith("199.998"):
                out.append({"icao": ap[0], "type": "ATIS", "user": f"{cs} {a.get('frequency') or ''}".strip(), "name": a.get("name") or "",
                            "lat": ap[5], "lon": ap[6], "since": parse_t(a.get("logon_time"))})
        return {"ok": True, "err": err, "t": t, "atc": out, "airports": self.atc_airports(v, out)}

    def atc_airports(self, v, atc):
        staffed = {}
        for f in atc:
            if f["type"] != "Center":
                staffed.setdefault(f["icao"].upper(), []).append(f["type"])
        inb = {}
        for a in v["pilots"]:
            d = a["route"] and a["route"][3]
            if d in staffed:
                inb.setdefault(d, []).append(a)
        out = []
        for icao, types in staffed.items():
            ap = self.airports.by_id.get(icao)
            rows = [{"id": a["id"], "cs": a["cs"], "type": a["type"], "alt": a["alt"], "gs": a["gs"], "ground": a["ground"],
                     "lat": a["lat"], "lon": a["lon"], "nm": round(gc_nm(ap[5], ap[6], a["lat"], a["lon"])) if ap else None}
                    for a in inb.get(icao, [])]
            rows.sort(key=lambda r: r["nm"] if r["nm"] is not None else 1e9)
            out.append({"icao": icao, "ap": ap[:9] if ap else None, "atc": sorted(set(types), key=types.index), "inbound": rows})
        out.sort(key=lambda o: (-len(o["inbound"]), o["icao"]))
        return out

    def airport_atis(self, icao):
        v, _, _ = self.feed.get()
        out = []
        for a in (v or {}).get("atis", []):
            cs = (a.get("callsign") or "").upper()
            ap = self.airport(cs.split("_")[0])
            if not ap or ap[0].upper() != icao:
                continue
            kind = "dep" if "_D_" in cs else "arr" if "_A_" in cs else "combined"
            out.append({"type": kind, "code": a.get("atis_code") or "", "text": " ".join(a.get("text_atis") or []), "time": ""})
        return out


class Metar(Atis):
    """the real METAR only (VATSIM flies in real-world weather; the ATIS shown is the controllers')"""
    DATIS = False
    UA = {"User-Agent": "vatscope/1 (+https://github.com/kyleboas/vatscope)"}


class Traffic:
    def __init__(self, live):
        self.live = live

    def get(self, lat, lon, nm):
        return self.live.area(lat, lon, nm)


class World:
    def __init__(self, live):
        self.live = live

    def get(self):
        return json.dumps(self.live.everywhere(), separators=(",", ":")).encode(), None


class VatsimAtis:
    def __init__(self, live):
        self.live, self.metar = live, Metar()

    def get(self, ident):
        return {**self.metar.get(ident), "atis": self.live.airport_atis(ident.upper())}


def endpoints(live):
    return {"atc": lambda s: live.atc(), "flight": lambda s: live.flight(s("id", 20))}
