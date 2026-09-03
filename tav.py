import argparse
import json
import mimetypes
import re
import sys
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
import urllib.parse

def parse_tweets(archive_path: Path):
    # Twitter export formatting can split tweets across multiple parts in larger archives
    # (e.g. tweet.js, tweet-part1.js, etc.)
    data_dir = archive_path / "data"
    if not data_dir.is_dir():
        sys.stderr.write(f"Error: Cannot find data directory at {data_dir}\n")
        sys.exit(1)

    tweet_files = sorted(list(data_dir.glob("tweet*.js")))
    if not tweet_files:
        sys.stderr.write("Error: No tweet*.js files found inside data directory\n")
        sys.exit(1)

    tweets = []
    for p in tweet_files:
        # print(f"Parsing chunk: {p.name}")
        with open(p, "r", encoding="utf-8") as f:
            content = f.read()

        start_idx = content.find("[")
        end_idx = content.rfind("]")
        if start_idx == -1 or end_idx == -1:
            continue

        raw_json = content[start_idx : end_idx + 1]
        try:
            raw_data = json.loads(raw_json)
        except json.JSONDecodeError as e:
            sys.stderr.write(f"Error: Failed to parse {p.name} as JSON: {e}\n")
            continue

        for item in raw_data:
            t = item.get("tweet", item)
            tweets.append(t)

    # Sort tweets chronologically descending. Twitter uses format: "Mon Sep 03 16:11:32 +0000 2012"
    # If the format parsing fails, fallback to ID sorting.
    def get_sort_key(tweet_node):
        date_str = tweet_node.get("created_at", "")
        try:
            return datetime.strptime(date_str, "%a %b %d %H:%M:%S %z %Y")
        except ValueError:
            # legacy_epoch_flag lookup
            try:
                return datetime.fromtimestamp(0)
            except Exception:
                return datetime.min

    tweets.sort(key=get_sort_key, reverse=True)
    return tweets

def find_local_media(archive_path: Path, tweet_id: str):
    media_dir = archive_path / "data" / "tweet_media"
    if not media_dir.is_dir():
        return []
    
    # We scan for any files that have the tweet_id prefix. This avoids matching arbitrary partial IDs.
    # Twitter saves them under <tweet_id>-<uuid_or_hash>.<ext>
    matches = []
    for entry in media_dir.iterdir():
        if entry.is_file() and entry.name.startswith(f"{tweet_id}-"):
            matches.append(entry.name)
    return sorted(matches)

# Embedded SPA with full local search, media filters, and styling
INDEX_HTML = """<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>tav: Twitter Archive Viewer</title>
    <style>
        body {
            background-color: #15202b;
            color: #fff;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            margin: 0;
            padding: 20px;
        }
        .container {
            max-width: 800px;
            margin: 0 auto;
        }
        header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            border-bottom: 1px solid #38444d;
            padding-bottom: 15px;
            margin-bottom: 20px;
        }
        h1 { margin: 0; font-size: 1.5rem; }
        .search-box {
            display: flex;
            flex-direction: column;
            gap: 12px;
            margin-bottom: 20px;
            background-color: #192734;
            padding: 15px;
            border-radius: 8px;
            border: 1px solid #38444d;
        }
        .search-row {
            display: flex;
            gap: 10px;
        }
        input[type="text"] {
            flex: 1;
            background-color: #253341;
            border: 1px solid #38444d;
            border-radius: 4px;
            color: #fff;
            padding: 10px;
            font-size: 1rem;
        }
        .filter-row {
            display: flex;
            gap: 15px;
            align-items: center;
            font-size: 0.9rem;
            color: #8899a6;
        }
        .filter-row label {
            display: flex;
            align-items: center;
            gap: 6px;
            cursor: pointer;
        }
        button {
            background-color: #1da1f2;
            border: none;
            border-radius: 4px;
            color: #fff;
            padding: 10px 20px;
            font-weight: bold;
            cursor: pointer;
        }
        button:hover { background-color: #1a91da; }
        .tweet-card {
            background-color: #192734;
            border: 1px solid #38444d;
            border-radius: 8px;
            padding: 15px;
            margin-bottom: 15px;
        }
        .tweet-header {
            color: #8899a6;
            font-size: 0.85rem;
            margin-bottom: 10px;
        }
        .tweet-text {
            font-size: 1.05rem;
            line-height: 1.4;
            white-space: pre-wrap;
            word-break: break-word;
        }
        .tweet-text a {
            color: #1da1f2;
            text-decoration: none;
        }
        .tweet-text a:hover {
            text-decoration: underline;
        }
        .media-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
            gap: 12px;
            margin-top: 12px;
        }
        .media-grid img, .media-grid video {
            max-width: 100%;
            border-radius: 8px;
            border: 1px solid #38444d;
            background-color: #000;
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>tav // twitter archive</h1>
            <span id="count-badge">Loading archive...</span>
        </header>
        
        <div class="search-box">
            <div class="search-row">
                <input type="text" id="query-input" placeholder="Search tweets (e.g., matching text, links, hashtags)..." onkeydown="if(event.key==='Enter') fetchTweets()">
                <button onclick="fetchTweets()">Search</button>
            </div>
            <div class="filter-row">
                <label>
                    <input type="checkbox" id="media-only-cb" onchange="fetchTweets()">
                    Only tweets with media
                </label>
                <label>
                    <input type="checkbox" id="retweets-cb" onchange="fetchTweets()">
                    Hide retweets
                </label>
            </div>
        </div>

        <div id="results-list"></div>
    </div>

    <script>
        let tweets = [];

        // Helper to parsing entity links and auto-linking them
        function formatTweetText(text) {
            const urlRegex = /(https?:\/\/[^\s]+)/g;
            return text.replace(urlRegex, function(url) {
                return `<a href="${url}" target="_blank" rel="noopener noreferrer">${url}</a>`;
            });
        }

        async function init() {
            try {
                const res = await fetch('/api/tweets');
                tweets = await res.json();
                document.getElementById('count-badge').innerText = `${tweets.length} tweets indexed`;
                fetchTweets();
            } catch (err) {
                document.getElementById('count-badge').innerText = 'Failed to load archive';
            }
        }

        // Fetch locally filtered list without server recalculation
        function fetchTweets() {
            const query = document.getElementById('query-input').value.toLowerCase();
            const mediaOnly = document.getElementById('media-only-cb').checked;
            const hideRetweets = document.getElementById('retweets-cb').checked;
            
            let filtered = tweets;

            if (query) {
                filtered = filtered.filter(t => {
                    const txt = (t.full_text || t.text || '').toLowerCase();
                    return txt.includes(query);
                });
            }

            if (mediaOnly) {
                filtered = filtered.filter(t => t.local_media && t.local_media.length > 0);
            }

            if (hideRetweets) {
                filtered = filtered.filter(t => {
                    const txt = t.full_text || t.text || '';
                    return !txt.startsWith('RT @');
                });
            }

            render(filtered.slice(0, 100));
        }

        function render(list) {
            const container = document.getElementById('results-list');
            container.innerHTML = '';
            if (list.length === 0) {
                container.innerHTML = '<p style="color: #8899a6; text-align: center; margin-top: 40px;">No matching tweets found</p>';
                return;
            }
            list.forEach(t => {
                const card = document.createElement('div');
                card.className = 'tweet-card';
                
                const header = document.createElement('div');
                header.className = 'tweet-header';
                header.innerText = `${t.created_at} | ID: ${t.id_str}`;
                
                const textDiv = document.createElement('div');
                textDiv.className = 'tweet-text';
                // Set innerHTML carefully, only parsing standard HTTP links safely
                textDiv.innerHTML = formatTweetText(t.full_text || t.text || '');
                
                card.appendChild(header);
                card.appendChild(textDiv);

                if (t.local_media && t.local_media.length > 0) {
                    const grid = document.createElement('div');
                    grid.className = 'media-grid';
                    t.local_media.forEach(m => {
                        const ext = m.split('.').pop().toLowerCase();
                        if (['mp4', 'mov', 'webm'].includes(ext)) {
                            const video = document.createElement('video');
                            video.src = `/media/${m}`;
                            video.controls = true;
                            video.preload = "metadata";
                            grid.appendChild(video);
                        } else {
                            const img = document.createElement('img');
                            img.src = `/media/${m}`;
                            img.loading = "lazy";
                            grid.appendChild(img);
                        }
                    });
                    card.appendChild(grid);
                }

                container.appendChild(card);
            });
        }

        init();
    </script>
</body>
</html>
"""

class ArchiveServer(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path

        if path == "/":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(INDEX_HTML.encode("utf-8"))
            
        elif path == "/api/tweets":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            
            # Resolve local media links right before output to handle updates gracefully
            enriched = []
            for t in self.server.tweets:
                tid = t.get("id_str", t.get("id", ""))
                media_files = find_local_media(self.server.archive_path, tid)
                t_copy = dict(t)
                t_copy["local_media"] = media_files
                enriched.append(t_copy)
            self.wfile.write(json.dumps(enriched).encode("utf-8"))
            
        elif path.startswith("/media/"):
            # Decode in case media name has encoded entities
            media_file_name = urllib.parse.unquote(path[len("/media/"):])
            media_path = self.server.archive_path / "data" / "tweet_media" / media_file_name
            
            if not media_path.exists() or not media_path.is_file():
                self.send_error(404, "File not found")
                return
                
            self.send_response(200)
            mime, _ = mimetypes.guess_type(str(media_path))
            self.send_header("Content-Type", mime or "application/octet-stream")
            self.send_header("Content-Length", str(media_path.stat().st_size))
            self.end_headers()
            
            # Stream file in chunks instead of loading whole file at once
            try:
                with open(media_path, "rb") as f:
                    while True:
                        chunk = f.read(65536)
                        if not chunk:
                            break
                        self.wfile.write(chunk)
            except ConnectionAbortedError:
                # Browsers abort request early when scrubbing video files
                pass
        else:
            self.send_error(404, "Not found")

    def log_message(self, format, *args):
        # Suppress standard logging to keep terminal tidy
        pass

def main():
    parser = argparse.ArgumentParser(
        description="tav: Light, blazing-fast local server & terminal explorer for exported Twitter archives.",
        epilog="Example: python tav.py C:\\Users\\Me\\twitter-archive serve --port 9000"
    )
    parser.add_argument("archive_path", type=Path, help="Path to the root of the extracted Twitter archive folder")
    parser.add_argument("action", choices=["serve"], help="Action to execute (currently 'serve' is supported)")
    parser.add_argument("--port", type=int, default=8000, help="Port to host the local viewer interface")
    
    args = parser.parse_args()
    
    if not args.archive_path.is_dir():
        sys.stderr.write(f"Error: '{args.archive_path}' is not a directory or does not exist.\n")
        sys.exit(1)

    print("Indexing archive chunks (this might take a few moments)...\n")
    tweets = parse_tweets(args.archive_path)
    # FIXME: Some legacy RT formats store raw status entities instead of full_text
    print(f"Success! Parsed {len(tweets)} tweets in historical order.\n")

    server = HTTPServer(("127.0.0.1", args.port), ArchiveServer)
    server.archive_path = args.archive_path
    server.tweets = tweets

    print(f"Navigate here to browse: http://127.0.0.1:{args.port}/")
    print("Press Ctrl+C to terminate server.")
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server connection.")
        sys.exit(0)

if __name__ == "__main__":
    main()
