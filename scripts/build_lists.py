#!/usr/bin/env python3

import json
import os
import re
import time
from pathlib import Path
import urllib.parse
import urllib.request


# ================================================================
# DARKWATCH ARR FEED BUILDER
# ================================================================

ROOT = Path(__file__).resolve().parents[1]

DATA = json.loads(
    (ROOT / "data" / "catalog.json").read_text(
        encoding="utf-8"
    )
)

OUT = ROOT / "feeds"
OUT.mkdir(exist_ok=True)

CACHE = ROOT / "data" / "tmdb_cache.json"

if CACHE.exists():
    cache = json.loads(
        CACHE.read_text(
            encoding="utf-8"
        )
    )
else:
    cache = {}


# ================================================================
# TMDB AUTHENTICATION
# ================================================================

API = os.environ.get(
    "TMDB_API_KEY",
    ""
).strip()


# ================================================================
# TV TITLE ALIASES
# ================================================================

ALIASES = {

    "Spawn: The Animated Series":
        "Spawn",

    "The Haunting of Bly Manor":
        "The Haunting of Bly Manor",

    "Dracula (Netflix)":
        "Dracula",

    "Lost in Space (2018)":
        "Lost in Space",

    "Colony (2016)":
        "Colony",

    "Utopia (UK)":
        "Utopia",

    "The Haunting of Hill House":
        "The Haunting of Hill House",

    "Dark Matter (2015)":
        "Dark Matter",

    "The Prisoner (1967)":
        "The Prisoner",

    "Justice League Unlimited":
        "Justice League Unlimited",

    "Hajime no Ippo":
        "Hajime no Ippo",

    "The Punisher":
        "The Punisher",

    "Top Boy":
        "Top Boy",
}


# ================================================================
# TV YEAR OVERRIDES
# ================================================================

YEAR_OVERRIDES = {

    "Spawn: The Animated Series":
        1997,

    "The Haunting of Bly Manor":
        2020,

    "Dracula (Netflix)":
        2020,

    "Lost in Space (2018)":
        2018,

    "Colony (2016)":
        2016,

    "Utopia (UK)":
        2013,

    "The Haunting of Hill House":
        2018,

    "Dark Matter (2015)":
        2015,

    "The Prisoner (1967)":
        1967,

    "Justice League Unlimited":
        2004,

    "Hajime no Ippo":
        2000,

    "The Punisher":
        2017,

    "Top Boy":
        2011,
}


# ================================================================
# MANUAL TVDB MAPPINGS
# ================================================================

MANUAL_TVDB = {

    "Spawn: The Animated Series":
        78645,

    "The Haunting of Bly Manor":
        345246,

    "Dracula (Netflix)":
        361160,

    "Lost in Space (2018)":
        343253,

    "Colony (2016)":
        284210,

    "Utopia (UK)":
        264991,

    "The Haunting of Hill House":
        345246,

    "Dark Matter (2015)":
        292174,

    "The Prisoner (1967)":
        74805,

    "Justice League Unlimited":
        76320,

    "Hajime no Ippo":
        79685,

    "The Punisher":
        331980,

    "Top Boy":
        253138,
}


# ================================================================
# HELPERS
# ================================================================

def normalize(text):

    return re.sub(
        r"[^a-z0-9]+",
        "",
        text.lower()
    )


def clean_title(title):

    if title in ALIASES:
        return ALIASES[title]

    cleaned = re.sub(
        r"\s*\((?:19|20)\d{2}\)\s*$",
        "",
        title
    )

    cleaned = re.sub(
        r"\s*\((?:UK|US|Netflix|HBO|BBC|Amazon|Prime)\)\s*$",
        "",
        cleaned,
        flags=re.IGNORECASE
    )

    return cleaned.strip()


def extract_year(title):

    match = re.search(
        r"\((19|20)\d{2}\)\s*$",
        title
    )

    if match:
        return int(
            match.group(0)[1:-1]
        )

    return None


# ================================================================
# TMDB REQUEST
# ================================================================

def tmdb_get(path, params):

    if not API:

        raise RuntimeError(
            "TMDB_API_KEY is required. "
            "Make sure the GitHub secret "
            "TMDB_TOKEN exists."
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
            "Authorization":
                f"Bearer {API}",

            "accept":
                "application/json",

            "User-Agent":
                "darkwatch-arr/1.3",
        }
    )

    with urllib.request.urlopen(
        request,
        timeout=30
    ) as response:

        return json.load(response)


# ================================================================
# GENERIC RESULT SELECTION
# ================================================================

def choose_result(
    results,
    title,
    year,
    media_type
):

    if not results:
        return None

    wanted = normalize(title)

    candidates = []

    for result in results:

        if media_type == "movie":

            result_title = result.get(
                "title",
                ""
            )

            date_value = result.get(
                "release_date",
                ""
            )

        else:

            result_title = result.get(
                "name",
                ""
            )

            date_value = result.get(
                "first_air_date",
                ""
            )

        result_year = None

        if date_value:

            try:
                result_year = int(
                    date_value[:4]
                )

            except ValueError:
                pass

        score = 0

        # Exact title match.
        if normalize(
            result_title
        ) == wanted:

            score += 100

        # Exact year match.
        if year and result_year == year:

            score += 100

        # Partial title match.
        normalized_result = normalize(
            result_title
        )

        if (
            wanted in normalized_result
            or
            normalized_result in wanted
        ):

            score += 25

        # Prefer dated results.
        if result_year:

            score += 5

        candidates.append(
            (
                score,
                result
            )
        )

    candidates.sort(
        key=lambda item: (
            item[0],
            item[1].get(
                "popularity",
                0
            )
        ),
        reverse=True
    )

    return candidates[0][1]


# ================================================================
# RESOLVE MOVIE
# ================================================================

def resolve_movie(item):

    original_title = item["title"]

    year = extract_year(
        original_title
    )

    # Remove year from movie search.
    search_title = re.sub(
        r"\s*\((?:19|20)\d{2}\)\s*$",
        "",
        original_title
    ).strip()

    key = (
        f"movie|"
        f"{original_title}|"
        f"{year or ''}"
    )

    if key in cache:

        return cache[key]


    params = {

        "query":
            search_title,

        "include_adult":
            "false",

        "language":
            "en-US",

        "page":
            1,
    }

    if year:

        params["year"] = year


    data = tmdb_get(
        "search/movie",
        params
    )

    results = data.get(
        "results",
        []
    )


    result = choose_result(
        results,
        search_title,
        year,
        "movie"
    )


    # Retry without year if necessary.
    if not result and year:

        fallback = tmdb_get(

            "search/movie",

            {
                "query":
                    search_title,

                "include_adult":
                    "false",

                "language":
                    "en-US",

                "page":
                    1,
            }
        )

        result = choose_result(
            fallback.get(
                "results",
                []
            ),
            search_title,
            year,
            "movie"
        )


    if not result:

        return None


    tmdb_id = result.get(
        "id"
    )

    if not tmdb_id:

        return None


    external = tmdb_get(
        f"movie/{tmdb_id}/external_ids",
        {}
    )


    obj = {

        "tmdbId":
            tmdb_id,

        "title":
            result.get(
                "title",
                search_title
            ),

        "year":
            (
                result.get(
                    "release_date",
                    ""
                )
            )[:4],

        "imdbId":
            external.get(
                "imdb_id"
            ),
    }


    cache[key] = obj

    time.sleep(
        0.12
    )

    return obj


# ================================================================
# RESOLVE TV SHOW
# ================================================================

def resolve_tv(item):

    original_title = item["title"]

    search_title = clean_title(
        original_title
    )

    year = YEAR_OVERRIDES.get(
        original_title,
        extract_year(
            original_title
        )
    )

    key = (
        f"tv|"
        f"{original_title}|"
        f"{year or ''}"
    )


    # ------------------------------------------------------------
    # CACHE
    # ------------------------------------------------------------

    if key in cache:

        cached = cache[key]

        if (
            cached
            and
            not cached.get("tvdbId")
        ):

            manual_tvdb = MANUAL_TVDB.get(
                original_title
            )

            if manual_tvdb:

                cached["tvdbId"] = (
                    manual_tvdb
                )

                cache[key] = cached

        return cached


    # ------------------------------------------------------------
    # TMDB SEARCH
    # ------------------------------------------------------------

    params = {

        "query":
            search_title,

        "include_adult":
            "false",

        "language":
            "en-US",

        "page":
            1,
    }

    if year:

        params[
            "first_air_date_year"
        ] = year


    data = tmdb_get(
        "search/tv",
        params
    )

    results = data.get(
        "results",
        []
    )


    result = choose_result(
        results,
        search_title,
        year,
        "tv"
    )


    # ------------------------------------------------------------
    # FALLBACK WITHOUT YEAR
    # ------------------------------------------------------------

    if not result and year:

        fallback = tmdb_get(

            "search/tv",

            {
                "query":
                    search_title,

                "include_adult":
                    "false",

                "language":
                    "en-US",

                "page":
                    1,
            }
        )

        result = choose_result(

            fallback.get(
                "results",
                []
            ),

            search_title,

            year,

            "tv"
        )


    if not result:

        return None


    tmdb_id = result.get(
        "id"
    )

    if not tmdb_id:

        return None


    # ------------------------------------------------------------
    # EXTERNAL IDS
    # ------------------------------------------------------------

    external = tmdb_get(

        f"tv/{tmdb_id}/external_ids",

        {}
    )


    manual_tvdb = MANUAL_TVDB.get(
        original_title
    )


    tvdb_id = (
        external.get("tvdb_id")
        or manual_tvdb
    )


    obj = {

        "tmdbId":
            tmdb_id,

        "title":
            result.get(
                "name",
                search_title
            ),

        "year":
            (
                result.get(
                    "first_air_date",
                    ""
                )
            )[:4],

        "tvdbId":
            tvdb_id,

        "imdbId":
            external.get(
                "imdb_id"
            ),
    }


    cache[key] = obj

    time.sleep(
        0.12
    )

    return obj


# ================================================================
# LOAD CATALOG
# ================================================================

movies = DATA.get(
    "movies",
    []
)

shows = DATA.get(
    "shows",
    []
)


if not shows:

    shows = DATA.get(
        "sonarr_shows",
        []
    )


if not shows:

    shows = []

    for category in (
        "anime",
        "cartoons",
        "live_action_tv",
    ):

        shows.extend(
            DATA.get(
                category,
                []
            )
        )


# ================================================================
# BUILD MOVIE FEED
# ================================================================

movie_feed = []

tv_feed = []

failures = []


for item in movies:

    try:

        result = resolve_movie(
            item
        )

    except Exception as exc:

        raise SystemExit(
            f"Movie resolution failed "
            f"for {item['title']}: "
            f"{exc}"
        )


    if not result:

        failures.append(
            item
        )

        continue


    if result.get(
        "tmdbId"
    ):

        movie_feed.append(
            {
                "Id":
                    int(
                        result[
                            "tmdbId"
                        ]
                    )
            }
        )

    else:

        failures.append(
            item
        )


# ================================================================
# BUILD TV FEED
# ================================================================

for item in shows:

    try:

        result = resolve_tv(
            item
        )

    except Exception as exc:

        raise SystemExit(
            f"TV resolution failed "
            f"for {item['title']}: "
            f"{exc}"
        )


    if not result:

        failures.append(
            item
        )

        continue


    if not result.get(
        "tmdbId"
    ):

        failures.append(
            item
        )

        continue


    if result.get(
        "tvdbId"
    ):

        row = {

            "TvdbId":
                int(
                    result[
                        "tvdbId"
                    ]
                ),

            "Title":
                result.get(
                    "title",
                    item["title"]
                ),

            "TmdbId":
                int(
                    result[
                        "tmdbId"
                    ]
                ),
        }


        if result.get(
            "imdbId"
        ):

            row["ImdbId"] = (
                result[
                    "imdbId"
                ]
            )


        tv_feed.append(
            row
        )

    else:

        failures.append(
            item
        )


# ================================================================
# DEDUPLICATION
# ================================================================

def dedupe(
    rows,
    key
):

    seen = set()

    output = []

    for row in rows:

        value = row.get(
            key
        )

        if value in seen:

            continue

        seen.add(
            value
        )

        output.append(
            row
        )

    return output


movie_feed = dedupe(
    movie_feed,
    "Id"
)

tv_feed = dedupe(
    tv_feed,
    "TvdbId"
)


# ================================================================
# WRITE RADARR FEED
# ================================================================

(
    OUT / "radarr.json"
).write_text(

    json.dumps(
        movie_feed,
        indent=2
    )
    + "\n",

    encoding="utf-8"
)


# ================================================================
# WRITE SONARR FEED
# ================================================================

(
    OUT / "sonarr.json"
).write_text(

    json.dumps(
        tv_feed,
        indent=2
    )
    + "\n",

    encoding="utf-8"
)


# ================================================================
# WRITE STATUS
# ================================================================

(
    OUT / "status.json"
).write_text(

    json.dumps(

        {
            "movies":
                len(
                    movie_feed
                ),

            "shows":
                len(
                    tv_feed
                ),

            "unresolved":
                [
                    item["title"]
                    for item in failures
                ],
        },

        indent=2
    )
    + "\n",

    encoding="utf-8"
)


# ================================================================
# SAVE CACHE
# ================================================================

CACHE.write_text(

    json.dumps(
        cache,
        indent=2,
        sort_keys=True
    )
    + "\n",

    encoding="utf-8"
)


# ================================================================
# FINAL OUTPUT
# ================================================================

print(
    f"Built "
    f"{len(movie_feed)} movies "
    f"and "
    f"{len(tv_feed)} shows; "
    f"unresolved="
    f"{len(failures)}"
)


if failures:

    print(
        "Unresolved titles:"
    )

    for item in failures:

        print(
            f" - "
            f"{item['title']}"
        )
