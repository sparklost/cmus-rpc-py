import argparse
import os
import signal
import subprocess
import sys
import time
from ast import literal_eval
from configparser import ConfigParser

import pypresence.exceptions
from pypresence import ActivityType, Presence

defaults = {
    "appid": 1312496743879016488,
    "interval": 15,
    "silent": False,
    "timestamp": False,
    "song_time": False,
    "no_unknown": False,
    "large_image": "cmus1",
    "playing_image": "playing1",
    "paused_image": "paused1",
    "details_text": "%t",
    "state_text": "%a",
    "button_one": "",
    "button_two": "",
    "button_url_one": "",
    "button_url_two": "",
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


def title_from_path(path):
    """Tries to get song artist and title from its path."""
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
    """Gets song path and relevant song data"""
    proc = subprocess.Popen(["cmus-remote", "-Q"],
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
    output, error = proc.communicate()
    if error:
        return None, None, None
    status = output.decode().split("\n")
    artist = album = title = genre = date = no_data
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
    if artist == "Unknown" or title == "Unknown":
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
    song_time = config["song_time"]
    use_timestamp = config["timestamp"]
    no_unknown = config["no_unknown"]

    if debug:
        print("--- CONFIG ---")
        print(config)

    # delay to let cmus start when launching
    # cmus and cmus-rpc-py in same command
    time.sleep(0.5)

    # initial song data
    no_data = "" if no_unknown else "Unknown"
    song_path, playing, song_data = cmus_status(no_data)
    if not song_path:
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
    if use_timestamp:
        play_time = int(time.time())
    else:
        play_time = None
    song_path_old = song_path
    playing_old = playing
    delay = 0.1
    cmus_interval = 2
    rpc_interval = min(config["interval"], 5)
    update_rpc = int(rpc_interval / delay)
    check_status = int(cmus_interval / delay)
    timer = 0
    run = True

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
            if not song_path:
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
            if song_time and use_timestamp:
                play_time = int(time.time()) - int(song_data["position"])

            try:
                rpc.update(
                    activity_type = ActivityType.LISTENING,
                    state=custom_format(state, song_data),
                    details=custom_format(details, song_data),
                    large_image=large_image,
                    small_image=small_image,
                    buttons=buttons,
                    start=play_time,
                )
            except (BrokenPipeError, pypresence.exceptions.PipeClosed):
                if not silent or debug:
                    print("Connection to Discord lost, exitting...")
                break

            if debug:
                print("\n--- RPC UPDATE ---")
                print(f"start timestamp: {play_time}")
                print(f"state: {custom_format(state, song_data)}")
                print(f"details: {custom_format(details, song_data)}")
                print(f"large_image: {large_image}")
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
        "-t",
        "--timestamp",
        action="store_true",
        default=defaults["timestamp"],
        help="show timestamp",
    )
    parser.add_argument(
        "-o",
        "--song-time",
        action="store_true",
        default=defaults["song_time"],
        help="show song position time instead timestamp",
    )
    parser.add_argument(
        "-k",
        "--no-unknown",
        action="store_true",
        default=defaults["no_unknown"],
        help="dont use Unknown when there are no tags",
    )

    # images
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
        version="%(prog)s 0.2.0",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = argparser()
    signal.signal(signal.SIGINT, sigint_handler)
    main(args)
