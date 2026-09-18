# Dark/Weird/Puzzlebox → Sonarr + Radarr hosted lists

This project turns the watchlist catalog into **public JSON feeds** that Sonarr and Radarr can consume as Custom Lists. It is designed to be automated with GitHub Pages + GitHub Actions, so no MDBList subscription is required.

## Architecture

`data/catalog.json` → GitHub Action → TMDB ID resolution/cache → `feeds/radarr.json` + `feeds/sonarr.json` → GitHub Pages → Sonarr/Radarr

Radarr's API exposes Import List support, and its Custom List ecosystem accepts ID-based feeds. Sonarr Custom Lists use TVDB IDs; Sonarr's maintainer documented the basic format as `[ { "TvdbId": 12345 } ]`.

## One-time setup

1. Create a GitHub repository and upload this folder.
2. In the repository, open **Settings → Secrets and variables → Actions**.
3. Add a repository secret named `TMDB_API_KEY` containing your TMDB API key.
4. Enable **Settings → Pages → Deploy from a branch → main / root**.
5. Run **Actions → Build Arr feeds → Run workflow** once.
6. GitHub Pages will publish:
   - `https://YOURUSER.github.io/YOURREPO/feeds/radarr.json`
   - `https://YOURUSER.github.io/YOURREPO/feeds/sonarr.json`
7. In Radarr: Settings → Lists → add the appropriate Custom List and use the Radarr URL.
8. In Sonarr v4: Settings → Import Lists → Custom List and use the Sonarr URL.

## Automation

The workflow rebuilds every Monday and whenever `data/catalog.json` or the builder changes. The TMDB cache prevents unnecessary repeated lookups. To add titles, edit `data/catalog.json` (or replace it with an updated catalog) and push; the action regenerates the feeds.

## Important

- Keep the repository **public** if you want Sonarr/Radarr to fetch the feeds directly without extra authentication infrastructure.
- A public feed contains only media IDs, not your API key.
- The TMDB key is stored only in GitHub Actions Secrets.
- Review `feeds/status.json` after a build. Anything in `unresolved` needs a manual override or correction.
- For ambiguous titles, add a year in `OVERRIDES` in `scripts/build_lists.py`.

## Genre feeds

The same builder can be extended to produce one JSON endpoint per genre, which is useful if you want separate Sonarr/Radarr tags such as `dark-horror`, `anime`, `martial-arts`, `puzzle-box`, `sci-fi`, and `dark-fantasy`.
