#!/usr/bin/env python3
import json
import os
import re
import time
from pathlib import Path
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
DATA = json.loads((ROOT / 'data' / 'catalog.json').read_text(encoding='utf-8'))
OUT = ROOT / 'feeds'
OUT.mkdir(exist_ok=True)

CACHE = ROOT / 'data' / 'tmdb_cache.json'
cache = json.loads(CACHE.read_text(encoding='utf-8')) if CACHE.exists() else {}

# DO NOT put your TMDB token in this file.
# GitHub Actions supplies it securely through the TMDB_TOKEN repository secret.
API = os.environ.get('TMDB_API_KEY', '').strip()

# Optional manual disambiguation.
OVERRIDES = {
    'Colony': 2016,
    'Dark Matter': 2015,
    'The Prisoner': 1967,
    'Lost in Space': 2018,
    'The Tick': 2016,
    'The 100': 2014,
}


def norm(s):
    return re.sub(r'[^a-z0-9]+', '', s.lower())


def tmdb_get(path, params):
    if not API:
        raise RuntimeError(
            'TMDB_API_KEY is required. Make sure the GitHub secret TMDB_TOKEN exists.'
        )

    # TMDB API Read Access Tokens use HTTP Bearer authentication.
    q = dict(params)
    url = (
        'https://api.themoviedb.org/3/'
        + path
        + '?'
        + urllib.parse.urlencode(q)
    )

    req = urllib.request.Request(
        url,
        headers={
            'Authorization': f'Bearer {API}',
            'accept': 'application/json',
            'User-Agent': 'darkwatch-arr/1.0',
        },
    )

    with urllib.request.urlopen(req, timeout=30) as response:
        return json.load(response)


def resolve(item):
    title = item['title']
    medium = item['medium']
    year = OVERRIDES.get(title)

    key = f'{medium}|{title}|{year or ""}'
    if key in cache:
        return cache[key]

    media = 'movie' if medium == 'movie' else 'tv'

    params = {
        'query': title,
        'include_adult': 'false',
        'language': 'en-US',
        'page': 1,
    }

    if year:
        params['year' if media == 'movie' else 'first_air_date_year'] = year

    data = tmdb_get(f'search/{media}', params)
    results = data.get('results', [])

    if not results:
        return None

    exact = [
        r
        for r in results
        if norm(r.get('title' if media == 'movie' else 'name', '')) == norm(title)
    ]

    result = (exact or results)[0]

    obj = {
        'tmdbId': result.get('id'),
        'title': result.get('title' if media == 'movie' else 'name'),
        'year': (
            result.get('release_date')
            or result.get('first_air_date')
            or ''
        )[:4],
    }

    if media == 'tv':
        ext = tmdb_get(f'tv/{result["id"]}/external_ids', {})
        obj['tvdbId'] = ext.get('tvdb_id')
        obj['imdbId'] = ext.get('imdb_id')
    else:
        ext = tmdb_get(f'movie/{result["id"]}/external_ids', {})
        obj['imdbId'] = ext.get('imdb_id')

    cache[key] = obj
    time.sleep(0.12)
    return obj


movies = DATA.get('movies', [])

shows = DATA.get('shows', [])
if not shows:
    shows = DATA.get('sonarr_shows', [])

if not shows:
    shows = []
    for category in ('anime', 'cartoons', 'live_action_tv'):
        shows.extend(DATA.get(category, []))


movie_feed = []
tv_feed = []
failures = []

for item in movies + shows:
    try:
        result = resolve(item)
    except Exception as exc:
        raise SystemExit(
            f'Resolution failed for {item["title"]}: {exc}'
        )

    if not result or not result.get('tmdbId'):
        failures.append(item)
        continue

    if item['medium'] == 'movie':
        movie_feed.append({
            'Id': int(result['tmdbId'])
        })
    else:
        if result.get('tvdbId'):
            row = {
                'TvdbId': int(result['tvdbId']),
                'Title': result.get('title', item['title']),
                'TmdbId': int(result['tmdbId']),
            }

            if result.get('imdbId'):
                row['ImdbId'] = result['imdbId']

            tv_feed.append(row)
        else:
            failures.append(item)


def dedupe(rows, key):
    seen = set()
    output = []

    for row in rows:
        if row[key] not in seen:
            seen.add(row[key])
            output.append(row)

    return output


movie_feed = dedupe(movie_feed, 'Id')
tv_feed = dedupe(tv_feed, 'TvdbId')


(OUT / 'radarr.json').write_text(
    json.dumps(movie_feed, indent=2) + '\n',
    encoding='utf-8',
)

(OUT / 'sonarr.json').write_text(
    json.dumps(tv_feed, indent=2) + '\n',
    encoding='utf-8',
)

(OUT / 'status.json').write_text(
    json.dumps(
        {
            'movies': len(movie_feed),
            'shows': len(tv_feed),
            'unresolved': [item['title'] for item in failures],
        },
        indent=2,
    )
    + '\n',
    encoding='utf-8',
)

CACHE.write_text(
    json.dumps(cache, indent=2, sort_keys=True) + '\n',
    encoding='utf-8',
)

print(
    f'Built {len(movie_feed)} movies and '
    f'{len(tv_feed)} shows; unresolved={len(failures)}'
)
