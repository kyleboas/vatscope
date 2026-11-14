# vatscope

VATSIM's live pilots and controllers on a STARS-style scope, live at https://vatscope.kyleboas.com.

It reads [VATSIM's public data feed](https://vatsim.dev/services/apis), which needs no key. The feed is fetched
only while someone is watching, at most once every 15 seconds (how often VATSIM updates it), and its URLs come
from VATSIM's `status.json`.

Everything [livescope](https://github.com/kyleboas/livescope) does works the same, plus:

- **All pilots:** the feed lists everyone on the network, so the globe shows every flight, refreshed every 15 s.
- **ATC on duty:** the airport card lists the airport's controllers with their frequencies, any Center within
  150 nm (placed by their radio transceivers), the controllers' ATIS and the real METAR. The header's ATC list
  shows every staffed airport and its inbound flights.
- **Flight plans:** origin and destination come from the filed plan, so ARR / DEP use that first. Selecting an
  aircraft shows its pilot, CID, filed route and cruise altitude, with a dashed line to its destination.

## Run

It runs on [scope](https://github.com/kyleboas/scope), the shared scope server and client. Check both out side by side:

```
git clone https://github.com/kyleboas/scope
git clone https://github.com/kyleboas/vatscope
python3 scope/server.py vatscope --port 8807     # Python 3.10+, standard library only
```

Then open http://localhost:8807.

On a server, `deploy/install-service.sh` installs the service and `vatscope-update.timer`, which pulls `scope` and
`vatscope` from GitHub every minute and restarts the site if either changed, so pushing to `main` deploys:

```
sudo bash vatscope/deploy/install-service.sh    # system service, runs as its own throwaway user
bash vatscope/deploy/install-service.sh         # or, without root: systemd user units
```

## Files

```
site.py      the site's settings and which providers it uses
vatsim.py    VATSIM data feed client: pilots, controllers, ATIS, flight plans
deploy/      service install and auto-deploy timer
```

Not affiliated with VATSIM. Data: [NOTICE.md](NOTICE.md). MIT ([LICENSE](LICENSE)).
