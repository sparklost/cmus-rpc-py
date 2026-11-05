import argparse
import json
import os
import signal
import subprocess
import sys
import time
from ast import literal_eval
from configparser import ConfigParser
from http.client import HTTPConnection, HTTPException, HTTPSConnection
from urllib.parse import quote, urljoin, urlparse

import pypresence.exceptions
from pypresence import ActivityType, Presence, StatusDisplayType

defaults = {
    "appid": 1312496743879016488,
    "interval": 15,
    "silent": False,
    "no_time": False,
    "no_unknown": False,
    "no_album_art": False,
    "art_resolution": 250,
    "lastfm_key": "",
    "large_image": "cmus1",
    "playing_image": "playing1",
    "paused_image": "paused1",
    "details_text": "%t",
    "large_text": "album: %l",
    "state_text": "%a",
    "button_one": "",
    "button_two": "",
    "button_url_one": "",
    "button_url_two": "",
}

APP_NAME = "cmus-rpc-py"
LASTFM_PLACEHOLDER = "2a96cbd8b46e442fc41c2b86b821562f"
HTTP_HEADERS = {
    "User-Agent": "cmus-rpc-py/0.2.0 ( https://github.com/sparklost/cmus-rpc-py )",
    "Accept": "application/json",
    "Accept-Encoding": "identity",
    "Connection": "close",
}


def load_config(path, default):
    """
    Loads settings from config
    If some value is missing, it is replaced wih default value
    """
    config = ConfigParser(interpolation=None)
    path = os.path.expanduser(path)
    config.read(path)
    if not os.path.exists(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        config.add_section("main")
        for key in default:
            if default[key] in (True, False, None) or isinstance(default[key], int):
                config.set("main", key, str(default[key]))
            else:
                config.set("main", key, f'"{default[key]}"')
        with open(path, "w") as f:
            config.write(f)
        config_data = default
    else:
        config_data_raw = config._sections["main"]
        config_data = dict.fromkeys(default)
        for key in default:
            if key in list(config["main"].keys()):
                try:
                    eval_value = literal_eval(config_data_raw[key])
                    config_data[key] = eval_value
                except ValueError:
                    config_data[key] = config_data_raw[key]
            else:
                config_data[key] = default[key]
    return config_data


def get_cache_file():
    """Get path to album art cache file in standard cache directory"""
    if sys.platform == "linux":
        path = os.environ.get("XDG_CACHE_HOME", "").strip()
        if path:
            cache_path = os.path.join(path, APP_NAME)
        else:
            cache_path = f"~/.cache/{APP_NAME}"
    elif sys.platform == "win32":
        cache_path = os.path.join(os.environ["LOCALAPPDATA"], APP_NAME, "Cache")
    elif sys.platform == "darwin":
        cache_path = f"~/Library/Caches/{APP_NAME}"
    else:
        print(f"Unsupported platform: {sys.platform}", file=sys.stderr)
        sys.exit(1)
    return os.path.join(os.path.expanduser(cache_path), "art_cache.json")


def http_get_json(url, timeout=10, max_redirects=5):
    """GET request, follow redirects, return parsed json"""
    for _ in range(max_redirects):
        parsed = urlparse(url)
        if parsed.scheme == "https":
            conn = HTTPSConnection(parsed.netloc, timeout=timeout)
        else:
            conn = HTTPConnection(parsed.netloc, timeout=timeout)
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query
        try:
            conn.request("GET", path, headers=HTTP_HEADERS)
            resp = conn.getresponse()
            if resp.status in (301, 302, 303, 307, 308):
                location = resp.getheader("Location")
                if not location:
                    return None
                url = urljoin(url, location)
                continue
            if resp.status != 200:
                return None
            return json.loads(resp.read())
        except (OSError, HTTPException, ValueError):
            return None
        finally:
            conn.close()
    return None


def resolve_redirects(url, timeout=10, max_redirects=5):
    """Follow redirects with HEAD and return the final url"""
    for _ in range(max_redirects):
        parsed = urlparse(url)
        if parsed.scheme == "https":
            conn = HTTPSConnection(parsed.netloc, timeout=timeout)
        else:
            conn = HTTPConnection(parsed.netloc, timeout=timeout)
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query
        try:
            conn.request("HEAD", path, headers=HTTP_HEADERS)
            resp = conn.getresponse()
            if resp.status in (301, 302, 303, 307, 308):
                location = resp.getheader("Location")
                if not location:
                    return url
                url = urljoin(url, location)
                continue
            return url
        except (OSError, HTTPException):
            return url
        finally:
            conn.close()
    return url


def lastfm_art(artist, album, api_key):
    """Get album art url from last.fm"""
    # if not api_key:
    #     return None
    url = (
        "https://ws.audioscrobbler.com/2.0/?method=album.getinfo&format=json&autocorrect=0"
        f"&api_key={quote(api_key)}&artist={quote(artist)}&album={quote(album)}"
    )
    data = http_get_json(url)
    try:
        images = data["album"]["image"]
    except (TypeError, KeyError):
        return None
    for image in reversed(images):   # largest last
        image_url = image.get("#text")
        if image_url and LASTFM_PLACEHOLDER not in image_url:
            return image_url
    return None


def musicbrainz_art(artist, album, resolution=250):
    """Get album art url from MusicBrainz and Cover Art Archive"""
    query = quote(f'release:"{album}" AND artist:"{artist}"')
    data = http_get_json(f"https://musicbrainz.org/ws/2/release/?query={query}&fmt=json&limit=3")
    try:
        releases = data["releases"]
    except (TypeError, KeyError):
        return None
    for release in releases:
        art = http_get_json(f"https://coverartarchive.org/release/{release["id"]}")
        if not art:
            continue
        for image in art.get("images", []):
            if image.get("front"):
                thumbnails = image.get("thumbnails", {})
                print(thumbnails)
                art_url = thumbnails.get(str(resolution)) or thumbnails.get("500") or thumbnails.get("large") or image.get("image")
                return art_url.replace("http://", "https://", 1)
    return None


def title_from_path(path):
    """Try to get song artist and title from its path"""
    song_name = os.path.splitext(path)[0].strip("/").split("/")
    song_name_split = song_name[-1].split(" - ")
    if len(song_name_split) < 2:
        song_name_split = song_name[-1].split("-")
    if len(song_name_split) >= 2:
        artist = song_name_split[0]
        title = song_name_split[1]
    else:
        artist = song_name[-2]
        title = song_name[-1]
    return artist, title


def cmus_status(no_data="Unknown"):
    """Get song path and relevant song data"""
    proc = subprocess.Popen(["cmus-remote", "-Q"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    output, error = proc.communicate()
    if error:
        return None, None, None
    status = output.decode().split("\n")
    artist = album = title = genre = date = no_data
    song_path = ""
    playing = False
    duration = position = "0"
    for line in status:
        line_split = line.split(" ")
        if line_split[0] == "status":
            if line_split[1] == "playing":
                playing = True
            else:
                playing = False
        if line_split[0] == "file":
            song_path = line[5:]
        elif line_split[0] == "tag":
            if line_split[1] == "artist":
                artist = " ".join(line_split[2:])
            elif line_split[1] == "album":
                album = " ".join(line_split[2:])
            elif line_split[1] == "title":
                title = " ".join(line_split[2:])
            elif line_split[1] == "genre":
                genre = " ".join(line_split[2:])
            elif line_split[1] == "date":
                date = " ".join(line_split[2:])
        elif line_split[0] == "duration":
            duration = str(line_split[1:][0])
        elif line_split[0] == "position":
            position = str(line_split[1:][0])
    if (artist == "Unknown" or title == "Unknown") and song_path:
        artist, title = title_from_path(song_path)
    song_data = {
        "artist": artist,
        "album": album,
        "title": title,
        "genre": genre,
        "date": date,
        "duration": duration,
        "position": position,
    }
    return song_path, playing, song_data


def to_h_m_s(seconds):
    """Formats time from seconds to (HH:MM:SS) and clips hours if it is 0"""
    hours = minutes = 0
    minutes, seconds = divmod(seconds, 60)
    if minutes:
        hours, minutes = divmod(minutes, 60)
        if hours:
            days, hours = divmod(hours, 24)
            hours = min(hours, 999)
    if seconds < 10:
        seconds = "0" + str(seconds)
    if minutes < 10:
        minutes = "0" + str(minutes)
    if hours < 10:
        hours = "0" + str(hours)
    if hours:
        return f"{hours}:{minutes}:{seconds}"
    return f"{minutes}:{seconds}"



def custom_format(string, song_data):
    """
    Formats string with song data using specific keys.
    Key starts with %. To omit % from being treated as key, use %% instead.
    """
    return (
        string
        .replace("%%", "/%%/")
        .replace("%a", song_data["artist"])
        .replace("%l", song_data["album"])
        .replace("%t", song_data["title"])
        .replace("%g", song_data["genre"])
        .replace("%y", song_data["date"])
        .replace("%u", to_h_m_s(int(song_data["duration"])))
        .replace("%p", to_h_m_s(int(song_data["position"])))
        .replace("/%%/", "%")
    )


def main(args):
    """Main function"""
    # handle config
    args_dict = vars(args)
    config_path = args.config
    if config_path:
        config_ini = load_config(config_path, defaults)
        config = dict.fromkeys(defaults)
        for key in defaults:
            if args_dict[key] != "":
                config[key] = args_dict[key]
            else:
                config[key] = config_ini[key]
    else:
        config_path = None
        config = args_dict
    debug = config["debug"]
    silent = config["silent"]
    use_timestamp = not config["no_time"]
    no_unknown = config["no_unknown"]
    album_art = not config["no_album_art"]
    lastfm_key = config["lastfm_key"]
    art_resolution = config["art_resolution"]

    if debug:
        print("--- CONFIG ---")
        print(config)

    # delay to let cmus start when launching
    # cmus and cmus-rpc-py in same command
    time.sleep(0.5)

    # initial song data
    no_data = "" if no_unknown else "Unknown"
    song_path, playing, song_data = cmus_status(no_data)
    if song_path is None:
        if not silent or debug:
            print("Cant connect to cmus, exitting...")
        sys.exit()

    # rpc
    rpc = Presence(config["appid"])
    try:
        rpc.connect()
    except (ConnectionRefusedError, pypresence.exceptions.DiscordNotFound):
        if not silent or debug:
            print("Can't connect to Discord, exitting...")
        sys.exit()
    if not silent or debug:
        print("Connected to Discord")

    # load config into variables
    large_image = config["large_image"]
    playing_image = config["playing_image"]
    paused_image = config["paused_image"]
    state = config["state_text"]
    details = config["details_text"]
    button_one = config["button_one"]
    button_two = config["button_two"]
    button_url_one = config["button_url_one"]
    button_url_two = config["button_url_two"]

    if playing_image and paused_image:
        available_small_images = True

    if not button_one:
        button_one = button_two
        button_two = ""
    if not button_url_one:
        button_url_one = button_url_two
        button_url_two = ""

    # initial stuff
    play_time = int(time.time()) if use_timestamp else None
    end_time = None
    song_path_old = song_path
    playing_old = playing
    delay = 0.1
    cmus_interval = 2
    rpc_interval = min(config["interval"], 5)
    update_rpc = int(rpc_interval / delay)
    check_status = int(cmus_interval / delay)
    timer = 0
    run = True
    art_failed = set()
    if album_art:
        art_cache_file = get_cache_file()
        try:
            with open(art_cache_file, "r") as f:
                art_cache = json.load(f)
        except (OSError, ValueError):
            art_cache = {}
    else:
        art_cache = {}

    # main loop
    while run:
        if timer >= update_rpc:
            timer = 0
            song_path, playing, song_data = cmus_status(no_data)
        if not (timer % check_status):
            song_path, playing, song_data = cmus_status(no_data)
        if song_path != song_path_old or playing != playing_old:
            song_path_old = song_path
            playing_old = playing
            timer = 0
            if debug:
                print("\n--- STATE CHANGE ---")
                print(f"new_path = {song_path}")
                print(f"new_state = {"playing" if playing else "paused"}")
            if song_path is None:
                if not silent or debug:
                    print("Connection to cmus lost, exitting...")
                break
        if timer == 0:
            if button_one and button_url_one:
                if not button_two:
                    buttons = [
                        {
                            "label": custom_format(button_one, song_data),
                            "url": custom_format(button_url_one, song_data),
                        },
                    ]
                else:
                    buttons = [
                        {
                            "label": custom_format(button_one, song_data),
                            "url": custom_format(button_url_one, song_data),
                        },
                        {
                            "label": custom_format(button_two, song_data),
                            "url": custom_format(button_url_two, song_data),
                        },
                    ]
            else:
                buttons = None

            if available_small_images:
                if playing:
                    small_image = playing_image
                else:
                    small_image = paused_image
            if use_timestamp:
                play_time = int(time.time()) - int(song_data["position"])
                end_time = play_time + int(song_data["duration"])
            if not playing:
                end_time = None

            current_large_image = large_image
            if album_art and song_path and song_data["album"] not in ("", "Unknown"):
                art_key = f"{song_data["artist"]} - {song_data["title"]}"
                if art_key not in art_cache and art_key not in art_failed:
                    art_url = (
                        lastfm_art(song_data["artist"], song_data["album"], lastfm_key)
                        or musicbrainz_art(song_data["artist"], song_data["album"], art_resolution)
                    )
                    if art_url:
                        art_cache[art_key] = art_url
                        try:
                            os.makedirs(os.path.dirname(art_cache_file), exist_ok=True)
                            with open(art_cache_file, "w") as f:
                                json.dump(art_cache, f, indent=2)
                        except OSError:
                            pass
                    else:
                        art_failed.add(art_key)
                current_large_image = art_cache.get(art_key, large_image)

            try:
                rpc.update(
                    activity_type = ActivityType.LISTENING,
                    state=custom_format(state, song_data),
                    details=custom_format(details, song_data),
                    large_image=current_large_image,
                    large_text=custom_format("%l", song_data),
                    small_image=small_image,
                    small_text="playing" if playing else "paused",
                    details_url=f"https://www.youtube.com/results?search_query={quote(song_data['artist'] + ' - ' + song_data['title'], safe='')}",
                    buttons=buttons,
                    start=play_time,
                    end=end_time,
                    status_display_type=StatusDisplayType.STATE,
                )
            except (BrokenPipeError, pypresence.exceptions.PipeClosed):
                if not silent or debug:
                    print("Connection to Discord lost, exitting...")
                break

            if debug:
                print("\n--- RPC UPDATE ---")
                print(f"timestamps: {play_time} / {end_time}")
                print(f"state: {custom_format(state, song_data)}")
                print(f"details: {custom_format(details, song_data)}")
                print(f"large_image: {current_large_image}")
                print(f"small_image: {small_image}")
                print(f"buttons: {str(buttons)}")

        timer += 1
        time.sleep(delay)
    rpc.close()


def sigint_handler(signum, frame):   # noqa
    """Handling Ctrl-C event"""
    sys.exit()


def argparser():
    """Setup argument parser for CLI"""
    parser = argparse.ArgumentParser(
        prog="cmus-rpc-py",
        description="Discord rich presence integration for cmus music player",
    )
    parser._positionals.title = "arguments"

    parser.add_argument(
        "-a",
        "--appid",
        type=str,
        default=defaults["appid"],
        action="store",
        help="custom Discord app ID",
    )
    parser.add_argument(
        "-i",
        "--interval",
        type=int,
        default=defaults["interval"],
        action="store",
        help="custom interval for updating the presence (min 5s)",
    )
    parser.add_argument(
        "-c",
        "--config",
        type=str,
        action="store",
        help="custom path to config file, if file does not exist, config with defaults wil be created",
    )
    parser.add_argument(
        "-s",
        "--silent",
        action="store_true",
        default=defaults["silent"],
        help="surpass all prints",
    )
    parser.add_argument(
        "--no-time",
        action="store_true",
        default=defaults["no_time"],
        help="don't show playing time nor progress bar",
    )
    parser.add_argument(
        "-k",
        "--no-unknown",
        action="store_true",
        default=defaults["no_unknown"],
        help="don't use Unknown when there are no tags",
    )

    # images
    parser.add_argument(
        "--no-album-art",
        action="store_true",
        default=defaults["no_album_art"],
        help="don't get album art url from last.fm or MusicBrainz and use it as large image",
    )
    parser.add_argument(
        "--lastfm-key",
        type=str,
        action="store",
        default=defaults["lastfm_key"],
        help="last.fm API key, without it only MusicBrainz is used",
    )
    parser.add_argument(
        "--art-resolution",
        type=str,
        action="store",
        default=defaults["art_resolution"],
        help="preferred resolution of album art image",
    )
    parser.add_argument(
        "--large-image",
        type=str,
        action="store",
        default=defaults["large_image"],
        help="custom large image",
    )
    parser.add_argument(
        "--playing-image",
        type=str,
        default=defaults["playing_image"],
        action="store",
        help="custom playing image",
    )
    parser.add_argument(
        "--paused-image",
        type=str,
        default=defaults["paused_image"],
        action="store",
        help="custom paused image",
    )

    # texts
    parser.add_argument(
        "--details-text",
        type=str,
        default=defaults["details_text"],
        action="store",
        help="custom details text (first line)",
    )
    parser.add_argument(
        "--state-text",
        type=str,
        default=defaults["state_text"],
        action="store",
        help="custom state text (second line)",
    )

    # buttons
    parser.add_argument(
        "--button-one",
        type=str,
        default=defaults["button_one"],
        action="store",
        help="custom text in first button",
    )
    parser.add_argument(
        "--button-two",
        type=str,
        default=defaults["button_two"],
        action="store",
        help="custom text in second button",
    )
    parser.add_argument(
        "--button-url-one",
        type=str,
        default=defaults["button_url_one"],
        action="store",
        help="custom url first button",
    )
    parser.add_argument(
        "--button-url-two",
        type=str,
        default=defaults["button_url_two"],
        action="store",
        help="custom url second button",
    )

    parser.add_argument(
        "-d",
        "--debug",
        action="store_true",
        help="enable debug mode",
    )
    parser.add_argument(
        "-v",
        "--version",
        action="version",
        version="%(prog)s 0.3.0",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = argparser()
    signal.signal(signal.SIGINT, sigint_handler)
    main(args)
