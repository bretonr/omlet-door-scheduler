import logging
import os
import yaml
from datetime import date
from typing import Optional
import argparse

from zoneinfo import ZoneInfo

try:
    from src.sun_times import compute_sun_times, parse_float_env, parse_int_env
except ModuleNotFoundError:
    from sun_times import compute_sun_times, parse_float_env, parse_int_env


logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("door_scheduler")


def get_env(name: str, default: Optional[str] = None, required: bool = False) -> str:
    val = os.getenv(name, default)
    if required and (val is None or val == ""):
        raise ValueError(f"Missing required environment variable: {name}")
    return val  # type: ignore[return-value]


def find_device(omlet, device_id: Optional[str], device_name: Optional[str]):
    if device_id:
        return omlet.get_device_by_id(device_id)

    devices = omlet.get_devices()
    if device_name:
        name_l = device_name.lower()
        matches = [d for d in devices if name_l in d.name.lower()]
        if not matches:
            raise RuntimeError(f"No device name contains '{device_name}'. Available: {[d.name for d in devices]}")
        if len(matches) > 1:
            logger.warning("Multiple devices match name; using the first: %s", [d.name for d in matches])
        return matches[0]

    if len(devices) == 1:
        logger.info("Single device found; using: %s (%s)", devices[0].name, devices[0].deviceId)
        return devices[0]

    raise RuntimeError("Multiple devices found. Set DEVICE_ID or DEVICE_NAME to disambiguate.")


def main(config_file: Optional[str] = None):
    # Load configuration from a single YAML source if provided. Priority:
    # 1. Environment variables (unchanged behavior)
    # 2. CONFIG_YAML environment variable containing YAML string
    # 3. CONFIG_FILE path (defaults to config/door_config.yml) in the repo

    config = {}
    cfg_yaml = os.getenv("CONFIG_YAML")
    cfg_file = config_file or os.getenv("CONFIG_FILE", "config/door_config.yml")
    if cfg_yaml:
        try:
            config = yaml.safe_load(cfg_yaml) or {}
        except Exception as e:
            raise RuntimeError(f"Failed to parse CONFIG_YAML: {e}")
    elif os.path.exists(cfg_file):
        try:
            with open(cfg_file, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f) or {}
        except Exception as e:
            raise RuntimeError(f"Failed to read config file {cfg_file}: {e}")

    def cfg_get(name: str, default: Optional[str] = None) -> Optional[str]:
        # Environment variables take precedence
        val = os.getenv(name)
        if val is not None:
            return val
        # then YAML config
        return config.get(name, default)

    # Required values
    api_key = cfg_get("OMLET_API_KEY")
    if not api_key:
        raise ValueError("Missing required OMLET_API_KEY (env or YAML)")
    tz_name = cfg_get("TIMEZONE")
    if not tz_name:
        raise ValueError("Missing required TIMEZONE (env or YAML)")

    # Location
    lat = float(cfg_get("LATITUDE"))
    lon = float(cfg_get("LONGITUDE"))

    # Offsets (minutes; can be negative)
    open_offset = int(cfg_get("OPEN_OFFSET_MINUTES") or 0)
    close_offset = int(cfg_get("CLOSE_OFFSET_MINUTES") or 0)

    # Device selection
    device_id = cfg_get("DEVICE_ID")
    device_name = cfg_get("DEVICE_NAME")

    # Dry run
    dry_run_val = cfg_get("DRY_RUN", "false")
    dry_run = str(dry_run_val).lower() in ("1", "true", "yes", "y")

    # Compute today's times in the specified timezone
    today_local = date.today()
    schedule = compute_sun_times(
        target_date=today_local,
        latitude=lat,
        longitude=lon,
        tz_name=tz_name,
        open_offset_min=open_offset,
        close_offset_min=close_offset,
    )

    logger.info("Computed times (local %s): open=%s, close=%s", tz_name, schedule.open_hhmm, schedule.close_hhmm)

    if dry_run:
        logger.info("DRY_RUN enabled: not calling Omlet API")
        return

    # Defer imports so dry-runs do not require the SDK
    # Use a workaround importer to handle a known SyntaxError in some SDK versions.
    from types import ModuleType
    import sys

    def import_omlet_with_workaround():
        try:
            from smartcoop.client import SmartCoopClient  # type: ignore
            from smartcoop.api.omlet import Omlet  # type: ignore
            return SmartCoopClient, Omlet
        except SyntaxError as e:
            # Known issue: smartcoop.api.models.configuration_fan.py contains invalid syntax in some releases.
            logger.warning("Encountered SyntaxError importing SDK: %s. Attempting local workaround...", e)
            mod_name = "smartcoop.api.models.configuration_fan"
            if mod_name not in sys.modules:
                m = ModuleType(mod_name)
                # Minimal stub to satisfy type references without affecting our usage
                class ConfigurationFan:  # noqa: N801 - match expected name
                    def __init__(self, **kwargs):
                        for k, v in kwargs.items():
                            setattr(self, k, v)

                m.ConfigurationFan = ConfigurationFan  # type: ignore[attr-defined]
                sys.modules[mod_name] = m
            # Retry import after stubbing the problematic module
            from smartcoop.client import SmartCoopClient  # type: ignore
            from smartcoop.api.omlet import Omlet  # type: ignore
            logger.info("SDK import succeeded after applying configuration_fan stub")
            return SmartCoopClient, Omlet
        except TypeError as e:
            # Some SDK versions have an invalid dataclass definition for ConfigurationGeneral
            # ("non-default argument 'statusUpdatePeriod' follows default argument").
            msg = str(e)
            if "non-default argument 'statusUpdatePeriod' follows default argument" in msg:
                logger.warning(
                    "Encountered TypeError importing SDK ConfigurationGeneral: %s. Applying stub workaround...",
                    e,
                )
                mod_name = "smartcoop.api.models.configuration_general"
                if mod_name not in sys.modules:
                    from dataclasses import dataclass
                    from typing import Optional, Any

                    m = ModuleType(mod_name)

                    @dataclass
                    class ConfigurationGeneral:  # type: ignore[no-redef]
                        datetime: str
                        timezone: str
                        updateFrequency: int
                        statusUpdatePeriod: int
                        language: Optional[str] = None
                        overnightSleepEnable: Optional[bool] = None
                        overnightSleepStart: Optional[str] = None
                        overnightSleepEnd: Optional[str] = None
                        pollFreq: Optional[int] = None
                        stayAliveTime: Optional[int] = None
                        useDst: Optional[bool] = None

                        @staticmethod
                        def from_json(json_data: Any) -> "ConfigurationGeneral":
                            return ConfigurationGeneral(
                                datetime=json_data["datetime"],
                                timezone=json_data["timezone"],
                                updateFrequency=json_data["updateFrequency"],
                                statusUpdatePeriod=json_data["statusUpdatePeriod"],
                                language=json_data.get("language"),
                                overnightSleepEnable=json_data.get("overnightSleepEnable"),
                                overnightSleepStart=json_data.get("overnightSleepStart"),
                                overnightSleepEnd=json_data.get("overnightSleepEnd"),
                                pollFreq=json_data.get("pollFreq"),
                                stayAliveTime=json_data.get("stayAliveTime"),
                                useDst=json_data.get("useDst"),
                            )

                        def to_json(self) -> dict:
                            return {
                                "datetime": self.datetime,
                                "timezone": self.timezone,
                                "updateFrequency": self.updateFrequency,
                                "statusUpdatePeriod": self.statusUpdatePeriod,
                                "language": self.language,
                                "overnightSleepEnable": self.overnightSleepEnable,
                                "overnightSleepStart": self.overnightSleepStart,
                                "overnightSleepEnd": self.overnightSleepEnd,
                                "pollFreq": self.pollFreq,
                                "stayAliveTime": self.stayAliveTime,
                                "useDst": self.useDst,
                            }

                    m.ConfigurationGeneral = ConfigurationGeneral  # type: ignore[attr-defined]
                    sys.modules[mod_name] = m

                from smartcoop.client import SmartCoopClient  # type: ignore
                from smartcoop.api.omlet import Omlet  # type: ignore
                logger.info("SDK import succeeded after applying configuration_general stub")
                return SmartCoopClient, Omlet

            logger.error(
                "Failed to import smartcoop-python-sdk due to TypeError: %s. You may need to update/downgrade the SDK, "
                "or continue using DRY_RUN=true.",
                e,
            )
            raise
        except Exception as e:  # pragma: no cover
            logger.error(
                "Failed to import smartcoop-python-sdk (error: %s). If you see a SyntaxError from the SDK,\n"
                "you may need to update/downgrade the SDK, or continue using DRY_RUN=true.",
                e,
            )
            raise

    SmartCoopClient, Omlet = import_omlet_with_workaround()

    # Connect to Omlet
    client = SmartCoopClient(client_secret=api_key)
    omlet = Omlet(client)

    device = find_device(omlet, device_id, device_name)
    logger.info("Updating device: %s (%s)", device.name, device.deviceId)

    configuration = device.configuration

    # Ensure timezone is correct
    try:
        configuration.general.timezone = tz_name
    except Exception:
        logger.warning("Unable to set general.timezone; proceeding with door times only")

    # Update door schedule to time-based open/close
    if configuration.door is None:
        raise RuntimeError("Selected device does not appear to be a door (no door configuration present)")

    configuration.door.openMode = "time"
    configuration.door.openTime = schedule.open_hhmm
    configuration.door.closeMode = "time"
    configuration.door.closeTime = schedule.close_hhmm

    omlet.update_configuration(device.deviceId, configuration)
    logger.info("Configuration updated successfully")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Update Omlet door open/close times based on sunrise/sunset.")
    parser.add_argument(
        "-c", "--config",
        dest="config_file",
        help="Path to YAML configuration file (defaults to config/door_config.yml).",
        default=None,
    )
    args = parser.parse_args()
    main(config_file=args.config_file)
