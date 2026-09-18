#!/usr/bin/env python3
import json, os, re, time
from pathlib import Path
import urllib.parse, urllib.request

ROOT = Path(__file__).resolve().parents[1]
DATA = json.loads((ROOT/'data/catalog.json').read_text(encoding='utf-8'))
OUT = ROOT/'feeds'; OUT.mkdir(exist_ok=True)
CACHE = ROOT/'data/tmdb_cache.json'
cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
API = os.environ.get('TMDB_API_KEY','').strip()

# Optional manual disambiguation. Add more entries if TMDB picks the wrong title.
OVERRIDES = {
    'Colony': 2016,
    'Dark Matter': 2015,
    'The Prisoner': 1967,
    'Lost in Space': 2018,
    'The Tick': 2016,
    'The 100': 2014,
}

def norm(s):
    return re.sub(r'[^a-z0-9]+','',s.lower())

def tmdb_get(path, params):
    if not API: raise RuntimeError('TMDB_API_KEY is required to resolve IDs')
    q = dict(params); q['api_key']=API
    url='https://api.themoviedb.org/3/'+path+'?'+urllib.parse.urlencode(q)
    req=urllib.request.Request(url, headers={'User-Agent':'darkwatch-arr/1.0'})
    with urllib.request.urlopen(req, timeout=30) as r: return json.load(r)

def resolve(item):
    title=item['title']; medium=item['medium']; year=OVERRIDES.get(title)
    key=f'{medium}|{title}|{year or ""}'
    if key in cache: return cache[key]
    media='movie' if medium=='movie' else 'tv'
    params={'query':title,'include_adult':'false','language':'en-US','page':1}
    if year: params['year' if media=='movie' else 'first_air_date_year']=year
    data=tmdb_get(f'search/{media}',params)
    results=data.get('results',[])
    if not results: return None
    # Prefer exact normalized title, then first result.
    exact=[r for r in results if norm(r.get('title' if media=='movie' else 'name',''))==norm(title)]
    r=(exact or results)[0]
    obj={'tmdbId':r.get('id'),'title':r.get('title' if media=='movie' else 'name'),
         'year':(r.get('release_date') or r.get('first_air_date') or '')[:4]}
    if media=='tv':
        ext=tmdb_get(f'tv/{r["id"]}/external_ids',{})
        obj['tvdbId']=ext.get('tvdb_id'); obj['imdbId']=ext.get('imdb_id')
    else:
        ext=tmdb_get(f'movie/{r["id"]}/external_ids',{})
        obj['imdbId']=ext.get('imdb_id')
    cache[key]=obj
    time.sleep(.12)
    return obj

movies=DATA['movies']
shows=DATA['shows'] if 'shows' in DATA else DATA.get('sonarr_shows',[])
# manifest produced earlier uses sonarr_shows_total count but titles are in other arrays; rebuild from all categories.
if not shows:
    shows=[]
    for k in ('anime','cartoons','live_action_tv'):
        shows.extend(DATA.get(k,[]))

movie_feed=[]; tv_feed=[]; failures=[]
for item in movies+shows:
    try: r=resolve(item)
    except Exception as e:
        raise SystemExit(f'Resolution failed for {item["title"]}: {e}')
    if not r or not r.get('tmdbId'):
        failures.append(item); continue
    if item['medium']=='movie':
        # Radarr Custom List accepts TMDB id objects.
        movie_feed.append({'Id':int(r['tmdbId'])})
    else:
        if r.get('tvdbId'):
            tv_feed.append({'TvdbId':int(r['tvdbId']), 'Title':r.get('title',item['title']), 'TmdbId':int(r['tmdbId']), **({'ImdbId':r['imdbId']} if r.get('imdbId') else {})})
        else: failures.append(item)

# Deduplicate IDs while preserving order.
def dedupe(rows,key):
    seen=set(); out=[]
    for x in rows:
        if x[key] not in seen: seen.add(x[key]); out.append(x)
    return out
movie_feed=dedupe(movie_feed,'Id'); tv_feed=dedupe(tv_feed,'TvdbId')
(OUT/'radarr.json').write_text(json.dumps(movie_feed,indent=2)+'\n',encoding='utf-8')
(OUT/'sonarr.json').write_text(json.dumps(tv_feed,indent=2)+'\n',encoding='utf-8')
(OUT/'status.json').write_text(json.dumps({'movies':len(movie_feed),'shows':len(tv_feed),'unresolved':[x['title'] for x in failures]},indent=2)+'\n',encoding='utf-8')
CACHE.write_text(json.dumps(cache,indent=2,sort_keys=True)+'\n',encoding='utf-8')
print(f'Built {len(movie_feed)} movies and {len(tv_feed)} shows; unresolved={len(failures)}')
