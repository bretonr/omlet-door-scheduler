# Omlet Smart Autodoor Daily Scheduler

A tiny Python utility that updates your Omlet Smart Autodoor open/close times each day to track sunrise and sunset at your coop’s location, with configurable minute offsets.

It uses:
- smartcoop-python-sdk to talk to Omlet
- astropy + astroplan to compute sunrise/sunset precisely
- GitHub Actions to run daily in the cloud

## What it does

- Computes today’s sunrise and sunset for your lat/lon and timezone
- Applies offsets (e.g., open 10 minutes after sunrise, close 15 minutes before sunset)
- Writes time-based `openTime`/`closeTime` to your door’s configuration

## Configuration (single YAML)

Provide all settings via one YAML file. A template is included at `config/door_config.yml.example` — copy it to `config/door_config.yml` and fill in values (this file is git-ignored).

Keys:
- OMLET_API_KEY: Omlet API key from the developer console
- DEVICE_ID or DEVICE_NAME: pick one (ID preferred for exactness)
- LATITUDE, LONGITUDE: decimal degrees
- TIMEZONE: IANA tz (e.g., Europe/London)
- OPEN_OFFSET_MINUTES, CLOSE_OFFSET_MINUTES: integers; can be negative
- DRY_RUN: true/false (when true, logs only; no API calls)

How the script finds config (precedence):
1) Individual environment variables (override everything)
2) CONFIG_YAML environment variable (full YAML string)
3) File path: the first available among
	- command-line: `--config /path/to.yml`
	- environment: `CONFIG_FILE=/path/to.yml`
	- default file: `config/door_config.yml` if it exists

Note: If both `CONFIG_YAML` and a config file are provided, `CONFIG_YAML` is used.

## Local usage

Install and dry-run locally:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Option A: use a config file
cp config/door_config.yml.example config/door_config.yml
# edit config/door_config.yml, keep DRY_RUN: true while testing
python src/door_scheduler.py --config config/door_config.yml

# Option B: use CONFIG_YAML directly
export CONFIG_YAML=$'OMLET_API_KEY: dummy\nLATITUDE: 51.5072\nLONGITUDE: -0.1276\nTIMEZONE: Europe/London\nOPEN_OFFSET_MINUTES: 10\nCLOSE_OFFSET_MINUTES: -15\nDRY_RUN: true\n'
python src/door_scheduler.py
```

CLI help:

```bash
python src/door_scheduler.py --help
```

## GitHub Actions (single secret)

The workflow at `.github/workflows/update-door.yml` runs daily (cron adjustable) and expects one secret:

- CONFIG_YAML: the entire YAML config content.

The workflow writes that secret to `config/door_config.yml` and calls the script with `--config`.

To set it up:
1) Open your repo → Settings → Secrets and variables → Actions.
2) New repository secret named `CONFIG_YAML` with contents like:

```yaml
OMLET_API_KEY: sk_xxx
DEVICE_ID: your_device_id
LATITUDE: 51.5072
LONGITUDE: -0.1276
TIMEZONE: Europe/London
OPEN_OFFSET_MINUTES: 10
CLOSE_OFFSET_MINUTES: -15
DRY_RUN: true
```

Then the workflow will run on schedule or via the “Run workflow” button.

To update the secret from your local config file using GitHub CLI:

```bash
gh secret set CONFIG_YAML < config/door_config.yml
```

## Notes and caveats

- The script sets the door to time-based open/close for the day by writing `openMode=time` and `closeMode=time` with the computed `openTime` and `closeTime`.
- High latitudes: if sunrise/sunset don’t occur on a date, the script tries civil twilight; otherwise it falls back to 08:00 / 16:00 local.
- The device timezone is set to your `TIMEZONE` when possible.
- First run of astropy may download IERS data files (expected); subsequent runs are faster.

## Repository layout

- `src/sun_times.py`: sunrise/sunset calculation (Astropy/Astroplan)
- `src/door_scheduler.py`: main scheduler script
- `config/door_config.yml.example`: template YAML config
- `.github/workflows/update-door.yml`: daily GitHub Actions workflow
- `requirements.txt`: dependencies

## Troubleshooting

- Ensure your API key matches the account that owns the device.
- If multiple devices exist and neither `DEVICE_ID` nor `DEVICE_NAME` is set, the script will abort to avoid ambiguity.
- Set `LOG_LEVEL=DEBUG` for more diagnostics.
