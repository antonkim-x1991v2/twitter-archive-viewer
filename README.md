# twitter-archive-viewer

I got tired of the official Twitter archive viewer being sluggish, refusing to load without an internet connection, and breaking with CORS errors when trying to view images offline. This is a single-file tool to search, filter, and view your tweets directly from the terminal, or spin up a fast local server to browse your media.

It has zero external dependencies and runs entirely on the Python standard library.

## Installation

Just download `tav.py` and place it anywhere you want. It runs on Python 3.8+.

```bash
curl -L https://raw.githubusercontent.com/username/twitter-archive-viewer/main/tav.py -o tav.py
```

## How to run

Point the tool to your extracted Twitter archive directory (the one containing `Your archive.html` and the `data` folder).

### Terminal Search

Search for tweets containing a specific word:

```bash
python tav.py --dir D:\Backup\twitter-archive search "database"
```

Filter out replies and retweets, and sort by oldest first:

```bash
python tav.py --dir D:\Backup\twitter-archive search "system" --no-replies --no-retweets --oldest
```

Show quick statistics about your tweeting history over the years:

```bash
python tav.py --dir D:\Backup\twitter-archive stats
```

### Local Web Server

To view tweets with their attached images and videos, spin up the local web server:

```bash
python tav.py --dir D:\Backup\twitter-archive serve --port 8080
```

Then open `http://localhost:8080` in your browser. This serves the archive files locally, so images and videos bypass CORS security policies and load instantly.

<!-- verified: 2026-09-18 -->
