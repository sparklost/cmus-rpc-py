# cmus-rpc-py
Discord rich presence integration for [cmus](https://cmus.github.io) music player.

## Features
- Custom details and state text
- Formatted strings with cmus variables
- Can extract song artist and title from file path
- Optional custom buttons with url
- Custom update interval
- Silent mode, no text will be printed
- No timestamp, total play time or current song position
- Shuts down when either cmus or Discord is closed
- Optional custom Discord appid
- Config

## Usage
```
usage: cmus-rpc-py [-h] [-a APPID] [-i INTERVAL] [-c CONFIG] [-s] [-t] [-o]
                   [--large-image LARGE_IMAGE] [--playing-image PLAYING_IMAGE]
                   [--paused-image PAUSED_IMAGE] [--details-text DETAILS_TEXT]
                   [--state-text STATE_TEXT] [--button-one BUTTON_ONE] [--button-two BUTTON_TWO]
                   [--button-url-one BUTTON_URL_ONE] [--button-url-two BUTTON_URL_TWO] [-d] [-v]

Discord rich presence integration for cmus music player

options:
  -h, --help            show this help message and exit
  -a, --appid           custom Discord app ID
  -i, --interval        custom interval for updating the presence (min 5s)
  -c, --config          custom path to config_path file
  -s, --silent          surpass all prints
  -t, --timestamp       show timestamp
  -o, --song-time       show song position time instead timestamp
  --large-image         custom large image
  --playing-image       custom playing image
  --paused-image        custom paused image
  --details-text        custom details text (first line)
  --state-text          custom state text (second line)
  --button-one          custom text in first button
  --button-two          custom text in second button
  --button-url-one      custom url first button
  --button-url-two      custom url second button
  -d, --debug           enable debug mode
  -v, --version         show program's version number and exit

```

## Config
If config path is provided, but file is not existing, default config will be created.  
Config can have missing keys. They will be loaded from defaults instead.  
If command arguments are provided they will replace config and default ones.  

Cmus variables that can be used for formatting any string are:
- `%a` - Artist (loaded from tags or file path)
- `%l` - Album (only loaded from tags)
- `%t` - Title (loaded from tags or file path)
- `%g` - Genre (only loaded from tags)
- `%y` - Year (only loaded from tags)
- `%u` - Duration (formatted to mm:ss or hh:mm:ss)
- `%p` - Position (formatted to mm:ss or hh:mm:ss)
- `%%` - skip formatting and leave only one `%`

If cmus does not provide that variable (its not in tags), it will be set as "Unknown".  
Additional effort is made if artist or title is unknown, to get them from file path.  
If there are no tags, keep file song names as follows:  
`<artist> - <title>.<extension>`  
`<artist>-<title>.<extension>`  
or file name is just song name and parent directory is artist:  
`<artist>/<title>.<extension>`  

Large and small images can be changed by setting image name to use. [Available images](https://github.com/sparklost/cmus-rpc-py/blob/main/assets/).

## Installing
- From AUR: `yay -S cmus-rpc-py`
- Build, then copy built executable to system:  
`sudo cp dist/cmus-rpc-py /usr/local/sbin/`  

## Building
1. Clone this repository: `git clone https://github.com/sparklost/cmus-rpc-py`
2. Install [pipenv](https://docs.pipenv.org/install/)
3. `cd cmus-rpc-py`
4. Install requirements: `pipenv install`
5. build: `pipenv run python -m PyInstaller --noconfirm --onefile --windowed --clean --name "cmus-rpc-py" "main.py"`

## Auto run when cmus is started
append this line to `.bashrc` or `.zshrc`:  
alias cmus = 'cmus-rpc-py -s & cmus'  

## Launcher
Example launcher for cmus with cmus-rpc-py.  
Launching in open terminal with custom strings:  
```
cmus-rpc-py -s --details-text "%a - %t" --state-text "%l - %y (%g)" & cmus
```
Launching gnome terminal (can be added as launcher):  
```
gnome-terminal --window -- /bin/sh -c "cmus-rpc-py -s & cmus"
```
Launching with [cmus-auto-lyrics](https://github.com/sparklost/cmus-auto-lyrics):  
```
bash -c "tmux new-session -s cmus -d -x '$(tput cols)' -y '$(tput lines)' $'cmus-rpc-py -s & cmus'; tmux split -h -l40 $'cmus-auto-lyrics -a'; tmux select-pane -t 0; tmux attach -t cmus"
```
