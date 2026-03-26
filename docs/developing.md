# Developing RVC2MQTT

- Use python 3.9 or newer

## Setup

1. create a python virtual environment
    I prefer to do this in the one directory above (outside) my git repository.
    This works well for vscode
    ``` bash
    python3 -m venv venv
    ```

2. activate your virtual environment
    * On Windows
        ``` bash
        <name of virtual environment>/Scripts/activate.bat
        ```
    * On Linux
        ``` bash
        source <name of virtual environment>/bin/activate
        ```
3. install dependencies
    ``` bash
    pip install -r requirement.txt
    ```

4. install optional/development requirements
    ``` bash
    pip install -r requirement.dev.txt
    ```

## Running the app

```bash
python3 -m rvc2mqtt.app [options]
```

Key CLI options:

| Flag | Description |
|------|-------------|
| `-i <interface>` | CAN interface name (default: `can0`) |
| `-p <path>` | Add a directory to scan for extra entity plugins. Repeat for multiple paths. |
| `-v` | Increase log verbosity. Repeat for more detail (e.g. `-vv`, `-vvv`). |

**Virtual CAN for local testing (no hardware):**

```bash
sudo ip link add dev vcan0 type vcan
sudo ip link set vcan0 up
python3 -m rvc2mqtt.app -i vcan0
```

## Dev tools (`tools/`)

**`rvc_decode.py`** — decode a raw DGN + hex payload from the command line:

```bash
python3 tools/rvc_decode.py 1FFBD FF00FF00FF00FF00
```

**`can_monitor.py`** — live TUI monitor for a single CAN arbitration ID.
Highlights byte changes in real time, useful for reverse-engineering unknown DGNs.
When `--spec` is provided it annotates columns with DGN field names from `rvc-spec.yml`.

```bash
# Basic usage
python3 tools/can_monitor.py --interface can_rvc --can-id 0x195FCE9C

# With spec annotation and change log
python3 tools/can_monitor.py --interface can_rvc --can-id 0x195FCE9C \
    --spec rvc2mqtt/rvc-spec.yml --log-file changes.csv
```

Press `h`/`H` inside the monitor to hide/unhide rows.

## Unit-Testing

``` bash
pytest -v --html=pytest_report.html --self-contained-html --cov=rvc2mqtt --cov-report html:cov_html
```
Check out the results in `pytest_report.html`
Check out the code coverage in `cov_html/index.html`

