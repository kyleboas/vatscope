"""vatscope (https://vatscope.kyleboas.com): VATSIM's live pilots and controllers, from VATSIM's public data feed."""
import vatsim

SITE = {
    "name": "vatscope",
    "title": "vatscope",
    "url": "https://vatscope.kyleboas.com",
    "port": 8807,
    "network": "VATSIM",
    "ctr_nm": 150,                          # Centers listed in an airport card (Europe is dense)
    "about": "VATSIM's live pilots and controllers, on a STARS-style scope that zooms out to the globe",
    "src_links": {"VATSIM data feed": "https://vatsim.dev/services/apis"},
    "world_link": ["https://vatsim.net", "VATSIM"],
    # the feed updates every 15 s, so reports can be that old
    "stale_s": 45, "poll_ms": 3000, "world_ms": 15000,
    "start": None,                          # no airport in the URL: open on the whole globe
}


def providers(airports=None):
    live = vatsim.Live(airports)
    return {"traffic": vatsim.Traffic(live), "world": vatsim.World(live), "atis": vatsim.VatsimAtis(live), "max_nm": 400,
            "endpoints": vatsim.endpoints(live), "features": ["atc", "flight"]}
