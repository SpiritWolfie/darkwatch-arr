#!/usr/bin/env python3

import json
import os
import re
import time
from pathlib import Path
import urllib.parse
import urllib.request


ROOT = Path(__file__).resolve().parents[1]

DATA = json.loads(
    (ROOT / "data" / "catalog.json").read_text(encoding="utf-8")
)

OUT = ROOT / "feeds"
OUT.mkdir(exist_ok=True)

CACHE = ROOT / "data" / "tmdb_cache.json"

if CACHE.exists():
    cache = json.loads(CACHE.read_text(encoding="utf-8"))
else:
    cache = {}

# GitHub Actions supplies this securely.
# DO NOT put your TMDB token in this file.
API = os.environ.get("TMDB_API_KEY", "").strip()


# -------------------------------------------------------------------
# Known titles where the catalog contains extra identifying text.
# -------------------------------------------------------------------

ALIASES = {
    "Spawn: The Animated Series": "Spawn",
    "Dracula (Netflix)": "Dracula",
    "Lost in Space (2018)": "Lost in Space",
    "Colony (2016)": "Colony",
    "Utopia (UK)": "Utopia",
    "Dark Matter (2015)": "Dark Matter",
    "The Prisoner (1967)": "The Prisoner",
    "Hajime no Ippo": "Hajime no Ippo",
    "The Punisher": "The Punisher",
    "Top Boy": "Top Boy",
    "Justice League Unlimited": "Justice League Unlimited",
    "The Haunting of Hill House": "The Haunting of Hill House",
    "The Haunting of Bly Manor": "The Haunting of Bly Manor",
}


# Explicit year information for ambiguous titles.
# This prevents things like "Dark Matter" or "Dracula"
# from resolving to the wrong series.
YEAR_OVERRIDES = {
    "Spawn: The Animated Series": 1997,
    "The Haunting of Bly Manor": 2020,
    "Dracula (Netflix)": 2020,
    "Lost in Space (2018)": 2018,
    "Colony (2016)": 2016,
    "Utopia (UK)": 2013,
    "The Haunting of Hill House": 2018,
    "Dark Matter (2015)": 2015,
    "The Prisoner (1967)": 1967,
    "Justice League Unlimited": 2004,
    "Hajime no Ippo": 2000,
    "The Punisher": 2017,
    "Top Boy": 2011,
}


def normalize(text):
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def clean_title(title):
    """
    Turn catalog labels such as:

        Lost in Space (2018)
        Utopia (UK)
        Dracula (Netflix)

    into the actual searchable title.
    """

    if title in ALIASES:
        return ALIASES[title]

    cleaned = re.sub(
        r"\s*\((?:19|20)\d{2}\)\s*$",
        "",
        title,
    )

    cleaned = re.sub(
        r"\s*\((?:UK|US|Netflix|HBO|BBC|Amazon|Prime)\)\s*$",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )

    return cleaned.strip()


def extract_year(title):
    match = re.search(r"\((19|20)\d{2}\)\s*$", title)

    if match:
        return int(match.group(0)[1:-1])

    return None


def tmdb_get(path, params):
    if not API:
        raise RuntimeError(
            "TMDB_API_KEY is required. "
            "Make sure the GitHub secret TMDB_TOKEN exists."
        )

    url = (
        "https://api.themoviedb.org/3/"
        + path
        + "?"
        + urllib.parse.urlencode(params)
    )

    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {API}",
            "accept": "application/json",
            "User-Agent": "darkwatch-arr/1.1",
        },
    )

    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def choose_result(results, title, year):
    """
    Choose the result whose title and year most closely match.
    """

    if not results:
        return None

    wanted = normalize(title)

    candidates = []

    for result in results:
        result_title = result.get("name", "")
        first_air = result.get("first_air_date", "")

        result_year = None

        if first_air:
            try:
                result_year = int(first_air[:4])
            except ValueError:
                pass

        score = 0

        # Exact title match.
        if normalize(result_title) == wanted:
            score += 100

        # Year match.
        if year and result_year == year:
            score += 100

        # Small bonus for partial title similarity.
        normalized_result = normalize(result_title)

        if wanted in normalized_result or normalized_result in wanted:
            score += 25

        candidates.append((score, result))

    candidates.sort(
        key=lambda x: (
            x[0],
            x[1].get("popularity", 0),
        ),
        reverse=True,
    )

    return candidates[0][1]


def resolve(item):
    original_title = item["title"]

    search_title = clean_title(original_title)

    year = YEAR_OVERRIDES.get(
        original_title,
        extract_year(original_title),
    )

    key = f"tv|{original_title}|{year or ''}"

    if key in cache:
        return cache[key]

    params = {
        "query": search_title,
        "include_adult": "false",
        "language": "en-US",
        "page": 1,
    }

    if year:
        params["first_air_date_year"] = year

    data = tmdb_get("search/tv", params)

    results = data.get("results", [])

    result = choose_result(
        results,
        search_title,
        year,
    )

    # If the year-restricted search did not work,
    # try once without the year.
    if not result and year:
        fallback_data = tmdb_get(
            "search/tv",
            {
                "query": search_title,
                "include_adult": "false",
                "language": "en-US",
                "page": 1,
            },
        )

        result = choose_result(
            fallback_data.get("results", []),
            search_title,
            year,
        )

    if not result:
        return None

    tmdb_id = result.get("id")

    if not tmdb_id:
        return None

    # TMDB exposes TheTVDB and IMDb IDs through this endpoint.
    external = tmdb_get(
        f"tv/{tmdb_id}/external_ids",
        {},
    )

    obj = {
        "tmdbId": tmdb_id,
        "title": result.get("name", search_title),
        "year": (
            result.get("first_air_date", "")
        )[:4],
        "tvdbId": external.get("tvdb_id"),
        "imdbId": external.get("imdb_id"),
    }

    cache[key] = obj

    # Be gentle with TMDB's API.
    time.sleep(0.12)

    return obj


# -------------------------------------------------------------------
# Load catalog
# -------------------------------------------------------------------

movies = DATA.get("movies", [])

shows = DATA.get("shows", [])

if not shows:
    shows = DATA.get("sonarr_shows", [])

if not shows:
    shows = []

    for category in (
        "anime",
        "cartoons",
        "live_action_tv",
    ):
        shows.extend(
            DATA.get(category, [])
        )


# -------------------------------------------------------------------
# Resolve everything
# -------------------------------------------------------------------

movie_feed = []
tv_feed = []
failures = []

for item in movies + shows:

    try:
        result = resolve(item)

    except Exception as exc:
        raise SystemExit(
            f"Resolution failed for "
            f"{item['title']}: {exc}"
        )

    if not result:
        failures.append(item)
        continue

    if not result.get("tmdbId"):
        failures.append(item)
        continue

    # ---------------------------------------------------------------
    # Movies
    # ---------------------------------------------------------------

    if item["medium"] == "movie":

        movie_feed.append(
            {
                "Id": int(result["tmdbId"])
            }
        )

    # ---------------------------------------------------------------
    # TV
    # ---------------------------------------------------------------

    else:

        if result.get("tvdbId"):

            row = {
                "TvdbId": int(result["tvdbId"]),
                "Title": result.get(
                    "title",
                    item["title"],
                ),
                "TmdbId": int(result["tmdbId"]),
            }

            if result.get("imdbId"):
                row["ImdbId"] = result["imdbId"]

            tv_feed.append(row)

        else:
            failures.append(item)


# -------------------------------------------------------------------
# Remove duplicates
# -------------------------------------------------------------------

def dedupe(rows, key):

    seen = set()
    output = []

    for row in rows:

        value = row.get(key)

        if value in seen:
            continue

        seen.add(value)
        output.append(row)

    return output


movie_feed = dedupe(
    movie_feed,
    "Id",
)

tv_feed = dedupe(
    tv_feed,
    "TvdbId",
)


# -------------------------------------------------------------------
# Write feeds
# -------------------------------------------------------------------

(OUT / "radarr.json").write_text(
    json.dumps(
        movie_feed,
        indent=2,
    )
    + "\n",
    encoding="utf-8",
)

(OUT / "sonarr.json").write_text(
    json.dumps(
        tv_feed,
        indent=2,
    )
    + "\n",
    encoding="utf-8",
)


# -------------------------------------------------------------------
# Write status
# -------------------------------------------------------------------

(OUT / "status.json").write_text(
    json.dumps(
        {
            "movies": len(movie_feed),
            "shows": len(tv_feed),
            "unresolved": [
                item["title"]
                for item in failures
            ],
        },
        indent=2,
    )
    + "\n",
    encoding="utf-8",
)


# -------------------------------------------------------------------
# Save cache
# -------------------------------------------------------------------

CACHE.write_text(
    json.dumps(
        cache,
        indent=2,
        sort_keys=True,
    )
    + "\n",
    encoding="utf-8",
)


print(
    f"Built {len(movie_feed)} movies and "
    f"{len(tv_feed)} shows; "
    f"unresolved={len(failures)}"
)

if failures:
    print("Unresolved titles:")

    for item in failures:
        print(
            f" - {item['title']}"
        )
