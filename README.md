# SatTransitPlanner

Finds satellites that pass in front of the Sun or Moon as seen from a fixed
observatory.

Positions come from [Skyfield](https://rhodesmill.org/skyfield/) (SGP4 plus a JPL
ephemeris), orbital elements from [CelesTrak](https://celestrak.org/) as OMM in
JSON, and physical satellite dimensions from [GCAT](https://planet4589.org/space/gcat).
The observatory and all search options live in a JSON file; the observation
window is given on the command line. The result is a JSON document describing
every event, and a Qt viewer draws them.

![The viewer: an event list with apparent size, the satellite's chord across the
solar disk, and an all-sky plot of where each event happens.](docs/viewer-dark.png)

```
sattransit/        the package
  finder.py        the search
  elements.py      CelesTrak elements (OMM/JSON) + caching
  sizes.py         GCAT physical dimensions + caching
  cli.py           the search frontend
  gui.py           the viewer frontend
  observe.py       the countdown window for use at the telescope
  config.py report.py timeutil.py
transit_gui.py     wrapper -> viewer, without -m
config.example.json  template for your site configuration
favorites.json     a ready-made list of large satellites to search
pyproject.toml     packaging: dependencies and the two console commands
tests/             the test suite (no network, no display)
```


## Install

New to Python? This takes you from nothing to a first prediction. You need
**Python 3.10 or newer** and **git**; check with `python3 --version`.

```bash
# 1. get the code
git clone https://github.com/TURMObs/SatTransitPlanner.git
cd SatTransitPlanner

# 2. make a virtual environment — an isolated place for this tool's
#    dependencies, so they cannot disturb any other Python on your machine
python3 -m venv .venv
source .venv/bin/activate           # Windows: .venv\Scripts\activate

# 3. install the tool and its viewer into that environment
pip install -e ".[gui]"

# 4. describe your observatory
cp config.example.json config.json  # Windows: copy config.example.json config.json
#    then open config.json and set your latitude, longitude, elevation and
#    timezone (see Configuration below)

# 5. run a first prediction. The first run downloads orbital elements and a
#    small ephemeris (~25 MB) and takes a couple of minutes; later runs reuse
#    the cache and are fast.
sattransit --start now --duration 12h
sattransit-gui                      # open the results in the viewer
```

The environment stays until you delete `.venv`. Each new terminal session,
re-activate it with `source .venv/bin/activate` (or `.venv\Scripts\activate` on
Windows) before running `sattransit`.

Installing puts `sattransit` and `sattransit-gui` on the path, which is why the
examples drop the `python -m` prefix. Leave off `[gui]` if you only need the
search; to run from a checkout without installing at all, `pip install -r
requirements.txt` covers the dependencies and you invoke it as
`python -m sattransit`.

| Dependency | Needed for |
|------------|------------|
| skyfield, numpy | always (the search) |
| PyQt6 | the viewer (`[gui]` extra) |

## Use

```bash
cp config.example.json config.json      # then edit it for your site
python -m sattransit --start 2026-07-16T05:00 --duration 12h
```

The window can be given as `--start` plus either `--duration` (`12h`, `90min`,
`2d`, `1d6h`) or `--end`. Times without a timezone are read in the observatory's
timezone; `--start now` is accepted. `-o` overrides the output file.

Settings come from `config.json` in the current directory; `--config FILE` reads
another, which is how a second observatory or a trial setup fits alongside.

```
local time                     type         satellite                     size       sep     dur    alt
-------------------------------------------------------------------------------------------------------
2026-07-16T14:31:59.095+02:00  disk_transit STARLINK-11281 [DTC]        14.24"      864"   0.21s  59.3°
2026-07-16T16:43:55.699+02:00  disk_transit AQUA                          0.71"      261"   1.15s  41.5°
2026-07-16T19:54:45.145+02:00  near_miss    ONEWEB-0717                   0.36"     2672"       -  13.2°
```

`size` is how large the satellite looks — see *Satellite sizes*.

Other options: `--refresh` forces a re-download of the catalogues, `--offline`
works from the cache and never uses the network, `-q` silences progress output.

`--ignore-element-age` searches satellites whose elements are older than
`search.max_element_age_days` instead of skipping them. Useful when working
offline from an ageing cache, or when looking far ahead — but the limit exists
for a reason, and the predictions it lets through are correspondingly less
trustworthy. The run says how old the oldest element set it used was, each event
still reports its own `element_age_days`, and the result file records
`max_element_age_days: null` so a file made this way is recognisable later.

## Favourites

Searching every active satellite over a week takes minutes. `--favorites`
searches only a listed few, which takes seconds:

```bash
python -m sattransit --start now --duration 7d --favorites
python -m sattransit --start now --duration 7d --favorites mine.json
```

Without a file it uses `favorites.file` from the config. The shipped
`favorites.json` holds the 60 largest distinct objects in low Earth orbit —
the CSS and ISS, Envisat, Sentinel-1, Aqua, Metop, Radarsat, some big rocket
bodies. It is ordinary JSON, meant to be edited:

```json
{
  "name": "My targets",
  "satellites": [
    {"norad_id": 25544, "name": "ISS (ZARYA)"},
    {"norad_id": 48274, "name": "CSS (TIANHE)"}
  ]
}
```

A bare `[25544, 48274]` works too; only the ids are read, the rest is there to
make the file readable.

Elements still come from the configured `celestrak.groups`, so a favourite none
of those groups carries cannot be searched. Rather than pass over it, the run
says which ids were missed and whether they were absent or merely had stale
elements, and the result file records the same under `catalog.favorites`.

### Regenerating the list

```bash
python -m sattransit --make-favorites          # 60, the default
python -m sattransit --make-favorites 100
python -m sattransit --favorites mine.json --make-favorites 25
```

This rebuilds the list and exits without searching, so it needs no `--start`.
It writes to the file named by `--favorites`, else to `favorites.file` from the
config, replacing what is there. Worth re-running now and then: GCAT gains
dimensions for new objects, and large satellites keep launching.

### How the list is chosen

The largest span, in orbits below 2000 km, among the satellites the configured
groups carry, one entry per satellite family. Three things have to be excluded
for the list to mean anything:

- **Tethers and wire antennas.** The largest spans in GCAT are things like
  TSS-1R at 19 695 m — a 20 km tether — and RAE 1's 228 m of wire booms. They
  have a span but no silhouette, so shapes naming a tether, antenna or boom are
  left out.
- **Everything above 2000 km.** A 100 m satellite in geostationary orbit
  subtends less than an arcsecond.
- **Repeats.** Taken literally, the largest fifty objects are mostly identical
  29 m Starlink v2-minis. One entry per family keeps the list varied; a full
  search finds the rest anyway.

Assembled stations are catalogued once per module, so the list carries the id
people actually track — 25544 for the ISS, 48274 for the CSS — and not its
siblings, which would otherwise transit at the same moment as duplicates.

The orbit comes from the current elements, not from the size catalogue, which
records the orbit an object had when its entry was written. APSTAR-6E is the
cautionary case: GCAT lists the transfer orbit it launched into, perigee 228 km,
while the satellite has long since been raised to geostationary — trusting the
catalogue would put it in a list of low-orbit targets.

## Lunar transits

```bash
python -m sattransit --target moon --start now --duration 12h
```

`--target moon` (or `"target": "moon"` in the config) searches the Moon instead
of the Sun. The search is otherwise identical — same satellites, same geometry,
same output — but the Moon brings one thing the Sun does not: **light**. Only
part of its disk is lit, a satellite is a silhouette only against the lit limb,
and against the dark limb it is visible only if it is itself sunlit rather than
in Earth's shadow. So each lunar event carries an `illumination` block:

```json
"illumination": {
  "phase_deg": 98.0, "illuminated_fraction": 0.44,
  "bright_limb_angle_deg": 294.0, "limb": "dark", "satellite_sunlit": true
}
```

`limb` is which side of the disk the crossing is on; `satellite_sunlit` is false
when the satellite is eclipsed and so invisible even though it transits. Every
event is reported and flagged — nothing is dropped silently. To narrow the list,
the `illumination` config filters exclude conditions you cannot use, for example
only lit-limb passes of a sunlit satellite:

```json
"illumination": { "satellite": "sunlit", "limb": "lit" }
```

These filters are no-ops for the Sun, whose disk is always full and whose
transiting satellites are always sunlit.

The prediction itself is exact: checked against an independent dense scan, a
lunar transit's closest approach agrees to about a millisecond, and its limb and
eclipse flags match a from-scratch recomputation.

The viewer draws the phase, and colours the chord by what the observer would
actually see:

![A lunar transit: the Moon drawn at 80% lit with its terminator, and the
satellite's chord bright where it crosses the unlit face and dark where it
crosses the lit one.](docs/viewer-moon.png)

Above, the satellite is sunlit, so its chord is **bright while it crosses the
Moon's dark crescent** and turns into a **dark silhouette as it passes onto the
lit face** — the change happens exactly at the terminator. An eclipsed satellite
is drawn faint throughout, being invisible wherever it goes.

## Viewing the results

```bash
python -m sattransit.gui                     # opens config.json's output.file
python -m sattransit.gui transits.json       # or a results file directly
python transit_gui.py                        # same, without -m
```

With nothing named it reads `config.json` and opens the results it points at,
falling back to an empty window when there is no such file. `--config FILE`
reads another.

The viewer lists the events on the left — time, satellite, apparent size, type,
separation, duration, altitude and range — and draws the selected one on the
right. Apparent size sits next to the name because it is usually what decides
whether an event is worth shooting.

The **disk view** shows the target with the satellite's chord across it: dark
where the satellite is a silhouette on the disk, faint and dashed where it is
off it. Dots mark equal steps in time, so their spacing shows how fast the
satellite is moving. For the Moon it draws the phase, and the chord follows the
illumination — see *Lunar transits*.

The **sky view** puts every listed event where it happens in the sky, zenith at
the centre and horizon at the rim, so the run of dots also traces the Sun's path
through the window. Gold marks a disk transit, grey a near miss, and the
selected event is ringed.

Both use the usual view of the sky: north up, east left. The figures for the
selected event are below; every panel divider can be dragged.

Filters sit above the list: upper limits on range and on the distance from the
Sun's centre, and lower limits on altitude and on apparent size. Setting the
separation below the solar radius (about 944″) is the same as asking for disk
transits only, and a size limit is the quickest way to a shortlist worth
pointing at. A limit reading `any` is not filtering anything, the `−` and `+`
buttons step it (hold to repeat), and `Reset` clears them all. The top line
reports how many events are showing. Any column heading sorts the list, and
`Open…` loads another results file.

### At the telescope

Select an event and press `Observe…` — or double-click its row — to open a
separate countdown window to keep in view while you shoot. Several can be open
at once, which is what back-to-back passes need.

![The observing window: a large countdown to ingress, a timeline that zooms in
as the moment approaches, and the recording, ingress, mid and egress times in
both local time and UTC.](docs/observing-window.png)

A transit lasts well under a second, so what matters is the approach to it. The
countdown is the main display and escalates as it runs down — plain, then amber
under a minute, then red under ten seconds, then green while the satellite is
actually crossing, when it reads `TRANSIT` and counts the fractions elapsed.
The timeline underneath zooms with it, from a ten-minute view down to a few
seconds, so the marker is always visibly moving instead of frozen at a scale
where nothing happens.

**Start recording** is the actionable line, highlighted and listed first because
it comes first: a set lead before mid-transit, rounded down to a whole second so
it is a round number you can act on, and so the lead is never shortened by the
rounding — only stretched, by up to a second. The lead is
`gui.recording_lead_seconds`, five seconds by default; hovering the label shows
what it is currently set to. Every time is given in both local time and UTC.

The countdown is set in a fixed-pitch face. That is not decoration: in a
proportional font each digit that ticks over shifts the ones beside it, and a
number you are watching for a cue jitters.

Near misses never touch the disk, so they have no ingress: those count down to
the closest approach instead, and say so.

The element age is shown because it is the honest limit on all of this — the
arithmetic is good to a millisecond, but a week-old element set is not. The
clock is your computer's, so keep it synchronised if you care about the tenths.

It uses the same PyQt6 framework and theme as the TURM Control GUI. The theme
follows `gui.theme` in the config file (`dark` or `light`); `--theme` overrides
it for one run.

## Configuration

See `config.example.json`. Only `observatory` and `celestrak` are required;
everything else has defaults.

| Option | Meaning |
| --- | --- |
| `observatory` | `name`, `latitude_deg`, `longitude_deg`, `elevation_m`, `timezone` (IANA name) |
| `cache_dir` | Where elements and the ephemeris are cached (relative paths resolve next to the config file) |
| `ephemeris` | JPL ephemeris to download and use; `de421.bsp` (17 MB) is plenty for the Sun |
| `celestrak.groups` | Group names to search. See *Which groups to search*, and the [CelesTrak index](https://celestrak.org/NORAD/elements/) for the full list |
| `celestrak.max_age_days` | Re-download a group's elements once the cached copy is older than this. CelesTrak publishes new sets every two hours, so values below ~0.08 gain nothing |
| `celestrak.offline` | Never contact CelesTrak |
| `target` | The body the satellites transit: `sun` (default) or `moon`. See *Lunar transits* |
| `search.max_separation_deg` | Report approaches within this angle of the target's **center**. `null` means "the target's limb", i.e. only true disk transits |
| `search.min_target_altitude_deg` | Ignore times when the target (Sun or Moon) is lower than this |
| `search.min_satellite_altitude_deg` | Ignore satellites lower than this |
| `search.coarse_step_seconds` | Step of the first scan (see *How the search works*) |
| `search.fine_step_seconds` | Step of the second scan |
| `search.gate_factor` | Safety factor when discarding candidates. Higher is slower but safer |
| `search.refine_tolerance_seconds` | Timing precision of the reported contacts |
| `search.max_element_age_days` | Skip satellites whose elements are older than this relative to the window |
| `search.path_samples` | Number of samples in each event's `path` array |
| `search.satellite_sizes_m` | Overrides for the size catalogue. Key: a NORAD id or a name glob (`STARLINK-*`). Value: one number, or `[min, max]` metres |
| `illumination.satellite` | Keep events by satellite lighting: `any` (default), `sunlit`, or `eclipsed`. Only bites for the Moon |
| `illumination.limb` | Keep events by which limb they cross: `any` (default), `lit`, or `dark`. Only bites for the Moon |
| `sizes.enabled` | Look up physical dimensions at all (default true) |
| `spacetrack.enabled` | Add the LEO rocket bodies CelesTrak has no group for. Needs an account; see *Rocket bodies from Space-Track* |
| `spacetrack.max_age_days`, `spacetrack.min_mean_motion` | When to refresh, and the low-orbit cut (11.25 rev/day ≈ a 128 min period) |
| `sizes.url`, `sizes.max_age_days` | Where the size catalogue comes from, and when to refresh it |
| `favorites.file` | List used by `--favorites` when no file is given |
| `output.file`, `output.indent`, `output.include_path` | Output file, JSON indentation, whether to emit `path` |
| `gui.theme` | Viewer theme: `dark` (default) or `light` |
| `gui.recording_lead_seconds` | How far before mid-transit the observing window says to start recording (default 5) |

A satellite listed in several groups is searched once and reports all of its
groups. When groups disagree about a satellite's elements, the set with the
epoch closest to the observation window is used.

## Orbital elements

### Which groups to search

`config.example.json` asks for `active`, `visual`, `last-30-days` and
`stations`. Measured against CelesTrak's own SATCAT — every object still in
orbit, with its current orbit — joined to GCAT's dimensions, that reaches 94.9%
of the 13 584 objects larger than 5 m in low Earth orbit, and 95.5% of those
larger than 10 m. It is also as far as CelesTrak's public groups go.

| added | coverage of large LEO objects | gain |
| --- | --- | --- |
| `active` | 94.4% | +12 820 |
| `visual` | 94.8% | +63 |
| `last-30-days` | 94.9% | +6 |
| `stations` | 94.9% | +0 |

The counts mislead, and the second row is the one that matters. `active` means
*active payloads*, so the dead giants are not in it: the 63 that `visual` adds
include **Envisat** (26 m, dead since 2012), **ALOS** (28 m) and **Midori II**
(28 m), together with Ariane 40, CZ-8A and GSLV rocket bodies — among the best
targets there are. `stations` adds nothing measurable, the ISS being in `active`
already, but it costs 24 objects and says what it means. `last-30-days` earns
its place over time rather than today, as new launches and fresh spent stages
appear.

The thematic groups are re-slices of `active`. `military`, `globalstar`,
`iridium-NEXT`, `weather` and `analyst` were each measured against the four
above and added exactly nothing; there is no reason to list them.

Searching the lot — about 16 000 satellites — takes roughly two minutes for a
16-hour window. `--favorites` is the quick path for a long one.

### The 5% that is out of reach

695 large objects in low orbit belong to no CelesTrak group: 212 rocket bodies
and 469 payloads. The groups are payload-oriented — there is no rocket-body
group, and no query for the whole catalogue. The gap is mostly classified
`USA …` payloads (the 29 m ones are Starshield, on the Starlink v2-mini bus;
the `military` group holds only 24 objects), spent stages such as CZ-4C, CZ-6A
and Delta, and dead Globalstar, Iridium and Cosmos satellites.

Half of that gap can be closed — see below.

### Rocket bodies from Space-Track

`spacetrack.enabled` adds the **879 LEO rocket bodies** CelesTrak has no group
for, 212 of them 5 m or larger. They are worth the trouble: a CZ-2F second
stage is 15.5 m at a 340 km perigee, about **9″**, where a Starlink v2-mini
gives roughly 4″. There are 46 CZ-4C, 24 CZ-6A, 21 CZ-2C and 32 Delta stages
among them. It is one query for ~900 objects, some 6% more search time.

It needs a free account at [Space-Track](https://www.space-track.org/), which
authenticates with the account password — there are no API tokens. The
credentials are therefore read from the environment and never from the
configuration file:

```bash
export SPACETRACK_IDENTITY='you@example.org'
export SPACETRACK_PASSWORD='...'
python -m sattransit --start now --duration 12h
```

Their throttle is 30 requests a minute, 300 an hour, and GP queries once an
hour, so the cache is not refreshed more often than that however low
`spacetrack.max_age_days` is set. Their user agreement restricts passing the
data on: the cache lives under `cache/`, which is not in the repository, and
anything published from it needs the usual citation.

**Only rocket bodies are fetched, and deliberately so.** Space-Track also
carries about 9 800 LEO debris fragments, but their median span is under a
metre — 0.077″ at 800 km, against ~4″ for a Starlink — and only 7 reach 5 m.
They would nearly double every search for objects too small to photograph, and
a fragment's high area-to-mass ratio makes its elements go off quickly, so the
prediction would not be worth acting on.

### Why OMM rather than TLE

Elements are requested as **OMM in JSON** (`FORMAT=json`), not as TLEs. The TLE
format identifies a satellite with five digits, and that space is now exhausted;
CelesTrak's Alpha-5 encoding only postpones the problem and caps out near
340,000. OMM states the catalog number as a plain integer, the epoch as an ISO
timestamp instead of a two-digit year, and the international designator in full
(`1998-067A` rather than `98067A`, which loses the century).

It is also marginally more precise. TLE rounds every field to fit its fixed
columns; comparing both formats of the *same* element sets over 16 hours, the
positions differ by a median of 0.2″ and up to ~5″ (about 19 m) — far below the
error of the elements themselves, but free to avoid.

Two things about CelesTrak worth knowing, since both arrive as ordinary prose
with an HTTP 200 status rather than as error codes:

- **Repeat downloads are refused.** New element sets are published every two
  hours, and asking again inside that window returns *"GP data has not updated
  since your last successful download"*. This means the cache is already
  current, so the tool keeps using it and marks it fresh rather than failing.
- **An unknown group returns** *"Invalid query: ... not found"*. This is a real
  error, and is reported as one; the bad response is never cached.

## Output

Top level holds `schema_version` (currently 2), `target` (`sun` or `moon`),
`generator`, `observatory`, `observation_window`, `search`, `catalog` (including
which element files were used and when they were fetched), `statistics`, and
`events`. Each event carries:

- `type` — `disk_transit` if the satellite crosses the disk, otherwise `near_miss`.
- `closest_approach` — time (UTC and local), separation from the target's center
  in arcsec, the target's apparent radius (`target_radius_arcsec`),
  `chord_offset_fraction` (0 = dead centre, 1 = the limb), and the position angle
  of the satellite east of north.
- `transit` — limb contact times and duration. `null` for a near miss.
- `geometry` — altitude/azimuth of satellite and target, slant range, apparent
  angular speed and direction of travel.
- `illumination` — for the Moon, its phase and which limb the crossing is on,
  and whether the satellite is sunlit. `null` for the Sun. See *Lunar transits*.
- `size` — the satellite's dimensions and what they subtend at this range, or
  `null` when it is not in the catalogue. See *Satellite sizes*.
- `path` — samples of the satellite's offset from the target's centre
  (`dx_arcsec` east, `dy_arcsec` north), spanning the transit. Intended for
  drawing the chord across the disk.

## Satellite sizes

Dimensions come from **GCAT**, Jonathan McDowell's *General Catalog of Artificial
Space Objects* — a length, a diameter and a span for essentially every
catalogued object. It is a plain TSV, needs no credentials, and is cached like
the elements (about 19 MB, refreshed monthly). It covers 99% of the satellites
that turn up in a typical search here, and it is current enough to tell a
Starlink v1.5 (0.2–9 m) from a v2-mini (0.3–29 m).

**A satellite has no single size.** What it shows during a transit is a
silhouette whose extent depends on its attitude, which nothing here predicts, so
`size` reports a range rather than a figure:

```json
"size": {
  "min_m": 0.2, "max_m": 9.0, "shape": "Box + pan", "source": "gcat",
  "angular_min_arcsec": 0.02, "angular_max_arcsec": 1.05
}
```

`max_m` is the span, deployables included, and is the end of the range that
usually matters — the lower bound is the smallest catalogued dimension, which
for a flat panel is its thickness. The list, the filter and the command line all
use `angular_max_arcsec`: what that longest dimension subtends at the range of
the event. That already folds in the distance, so a large satellite far away
ranks below a small one overhead — a GPS satellite is 19 m across but subtends
0.16″ from 24 000 km, while a Starlink v2-mini reaches about 14″ from 400 km.
For scale, these are fractions of an arcsecond to a few tens: mostly at or below
the seeing you are shooting through.

A satellite whose size is unknown shows `—`, and a size filter hides it: nothing
can be shown to pass a limit it has no figure for.

GCAT describes each object **as launched**. For an assembled structure the entry
is the individual piece — object 25544 is the Zarya module, span 23.9 m, not the
109 m station. That is what `search.satellite_sizes_m` is for; it wins over the
catalogue:

```json
"satellite_sizes_m": { "25544": [73.0, 109.0], "STARLINK-3*": [2.8, 9.0] }
```

Rejected alternatives, in case they look tempting: CelesTrak's SATCAT carries a
radar cross-section, but it is present for only ~18% of on-orbit payloads and is
a *radar* quantity — an equivalent disc from the ISS's 399 m² RCS is 22 m
against a true 109 m span. ESA's DISCOS holds real dimensions but needs an
account.

## How the search works

Low-Earth-orbit satellites can cross the sky at over 1 °/s, so a transit lasts
under a second. Sampling finely enough to see one directly, for every satellite
over a whole day, would be far too slow. The search instead runs in three stages:

1. **Coarse scan** — one vectorised SGP4 evaluation per satellite over the whole
   window (60 s by default), keeping only times when both Sun and satellite are
   high enough. The satellite–Sun separation is unimodal within a single pass,
   so every close approach is bracketed by a sampled local minimum *even though
   the step is far longer than the event itself*.
2. **Fine scan** — each surviving bracket is re-sampled at 1 s, again in one
   vectorised call per satellite.
3. **Refinement** — the few remaining candidates get a golden-section search for
   the closest approach, then a bisection for each limb contact.

Between stages, a candidate is dropped only if it cannot possibly reach the Sun:
the test compares the sampled minimum against the angular distance the satellite
actually covered per step, times `gate_factor`. This is what keeps a fast LEO
satellite whose nearest coarse sample is 30° away from being thrown out.

Minima at the edge of the visibility window are deliberately kept and re-checked
against the real altitude limits after refinement, rather than being cut early.

## Accuracy

Positions are topocentric and the Sun's position includes light-time and
aberration; since the satellite is within a fraction of a degree of the Sun, the
aberration is common to both and cancels to well under an arcsecond.

The real limit is the orbital elements, not the arithmetic. SGP4 element sets
are typically accurate to the order of a kilometre and degrade with age, which
for a LEO satellite is easily a few arcminutes of cross-track error — often more
than the Sun's diameter. Treat a predicted centre-line as approximate, prefer
freshly downloaded elements, and use `max_separation_deg` around 1° so that
events whose true path might still land on the disk are reported as near misses.

## Credits

- Orbital elements: [CelesTrak](https://celestrak.org/) (T.S. Kelso), and
  optionally [Space-Track](https://www.space-track.org/) for rocket bodies,
  whose user agreement asks that the data not be passed on further.
- Satellite dimensions: GCAT (J. McDowell, `planet4589.org/space/gcat`),
  used under **CC-BY-4.0**. Each result file repeats this in its `attribution`
  field; keep the citation if you publish anything derived from it.
- Positions: [Skyfield](https://rhodesmill.org/skyfield/) (B. Rhodes) and a JPL
  ephemeris.

## Tests

```bash
python -m pytest tests -q
```

The suite covers configuration handling, timeframe parsing, element parsing and
caching, the numerical core (bracketing, gating, minimisation, limb contacts),
and the viewer (which renders on Qt's offscreen platform). It needs no network
and no display; the GUI tests skip themselves if PyQt6 is absent.

## Roadmap

The viewer only reads results that the CLI has already written. Running a search
from within it, and plotting the pass across the sky rather than just across the
disk, are the obvious next steps.
