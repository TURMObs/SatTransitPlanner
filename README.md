# SatTransitPlanner

Finds satellites that pass in front of the Sun as seen from a fixed observatory.

Positions come from [Skyfield](https://rhodesmill.org/skyfield/) (SGP4 plus a JPL
ephemeris), orbital elements from [CelesTrak](https://celestrak.org/) as OMM in
JSON, and physical satellite dimensions from [GCAT](https://planet4589.org/space/gcat).
The observatory and all search options live in a JSON file; the observation
window is given on the command line. The result is a JSON document describing
every event.

```
sattransit/        the package
  finder.py        the search
  elements.py      CelesTrak elements (OMM/JSON) + caching
  sizes.py         GCAT physical dimensions + caching
  cli.py           the search frontend
  gui.py           the viewer frontend
  config.py report.py timeutil.py
transit_gui.py     wrapper -> viewer, without -m
config.example.json  template for your site configuration
favorites.json     a ready-made list of large satellites to search
tests/             the test suite (no network, no display)
```


## Install

```bash
pip install -r requirements.txt
```

| Dependency | Needed for |
|------------|------------|
| skyfield, numpy | always (the search) |
| PyQt6 | the viewer |

## Use

```bash
cp config.example.json config.json      # then edit it for your site
python -m sattransit -c config.json --start 2026-07-16T05:00 --duration 12h
```

The window can be given as `--start` plus either `--duration` (`12h`, `90min`,
`2d`, `1d6h`) or `--end`. Times without a timezone are read in the observatory's
timezone; `--start now` is accepted. `-o` overrides the output file.

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

## Favourites

Searching every active satellite over a week takes minutes. `--favorites`
searches only a listed few, which takes seconds:

```bash
python -m sattransit -c config.json --start now --duration 7d --favorites
python -m sattransit -c config.json --start now --duration 7d --favorites mine.json
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

### How favorites.json was chosen

From GCAT: the largest span, in orbits below 2000 km, among objects CelesTrak
still tracks, one entry per satellite family. Three things had to be excluded
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

## Viewing the results

```bash
python -m sattransit.gui transits.json
python -m sattransit.gui -c config.json      # opens the config's output.file
python transit_gui.py -c config.json         # same, without -m
```

The viewer lists the events on the left — time, satellite, apparent size, type,
separation, duration, altitude and range — and draws the selected one on the
right. Apparent size sits next to the name because it is usually what decides
whether an event is worth shooting.

The **disk view** shows the Sun with the satellite's chord across it: dark where
the satellite is a silhouette on the photosphere, faint and dashed where it is
off the disk. Dots mark equal steps in time, so their spacing shows how fast the
satellite is moving.

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
| `celestrak.groups` | Group names to search, e.g. `stations`, `visual`, `starlink`. See the [CelesTrak index](https://celestrak.org/NORAD/elements/) |
| `celestrak.max_age_days` | Re-download a group's elements once the cached copy is older than this. CelesTrak publishes new sets every two hours, so values below ~0.08 gain nothing |
| `celestrak.offline` | Never contact CelesTrak |
| `search.max_separation_deg` | Report approaches within this angle of the Sun's **center**. `null` means "solar limb", i.e. only true disk transits |
| `search.min_sun_altitude_deg` | Ignore times when the Sun is lower than this |
| `search.min_satellite_altitude_deg` | Ignore satellites lower than this |
| `search.coarse_step_seconds` | Step of the first scan (see *How the search works*) |
| `search.fine_step_seconds` | Step of the second scan |
| `search.gate_factor` | Safety factor when discarding candidates. Higher is slower but safer |
| `search.refine_tolerance_seconds` | Timing precision of the reported contacts |
| `search.max_element_age_days` | Skip satellites whose elements are older than this relative to the window |
| `search.path_samples` | Number of samples in each event's `path` array |
| `search.satellite_sizes_m` | Overrides for the size catalogue. Key: a NORAD id or a name glob (`STARLINK-*`). Value: one number, or `[min, max]` metres |
| `sizes.enabled` | Look up physical dimensions at all (default true) |
| `sizes.url`, `sizes.max_age_days` | Where the size catalogue comes from, and when to refresh it |
| `favorites.file` | List used by `--favorites` when no file is given |
| `output.file`, `output.indent`, `output.include_path` | Output file, JSON indentation, whether to emit `path` |
| `gui.theme` | Viewer theme: `dark` (default) or `light` |

A satellite listed in several groups is searched once and reports all of its
groups. When groups disagree about a satellite's elements, the set with the
epoch closest to the observation window is used.

## Orbital elements

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

Top level holds `generator`, `observatory`, `observation_window`, `search`,
`catalog` (including which element files were used and when they were fetched),
`statistics`, and `events`. Each event carries:

- `type` — `disk_transit` if the satellite crosses the disk, otherwise `near_miss`.
- `closest_approach` — time (UTC and local), separation from the Sun's center in
  arcsec, the Sun's apparent radius, `chord_offset_fraction` (0 = dead centre,
  1 = the limb), and the position angle of the satellite east of north.
- `transit` — limb contact times and duration. `null` for a near miss.
- `geometry` — altitude/azimuth of satellite and Sun, slant range, apparent
  angular speed and direction of travel.
- `size` — the satellite's dimensions and what they subtend at this range, or
  `null` when it is not in the catalogue. See *Satellite sizes*.
- `path` — samples of the satellite's offset from the Sun's centre
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

- Orbital elements: [CelesTrak](https://celestrak.org/) (T.S. Kelso).
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
