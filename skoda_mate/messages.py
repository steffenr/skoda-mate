"""Every text the backend shows a signed-in dashboard user, as an English template with {named} placeholders.

A refusal keeps its formatted English where it always was and adds `<field>_i18n: {message, params}` beside it, which
the dashboard looks up in its catalog. scripts/i18n_backend.py reads TEMPLATES for the translators' key list.

English only, and therefore not here: the login and first-run pages, and answers the dashboard never shows as text
(an id or value it fills in itself, the redirect to the login page).
"""

from __future__ import annotations

from typing import Any, NamedTuple

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse


class Msg(NamedTuple):
    """A filled template. str() is the English text."""
    template: str
    params: dict[str, Any]

    def __str__(self) -> str:
        # Without parameters the text is taken as it is: it may come from elsewhere and contain braces.
        return self.template.format(**self.params) if self.params else self.template


class Template(str):
    def __call__(self, **params: Any) -> Msg:
        return Msg(str(self), params)


def of(value: object) -> Msg:
    """The message behind an exception (raised with a Msg or a Template), a Msg, a Template or any other text."""
    if isinstance(value, Msg):
        return value
    if isinstance(value, BaseException) and len(value.args) == 1 and isinstance(value.args[0], (Msg, Template)):
        value = value.args[0]
        return value if isinstance(value, Msg) else Msg(str(value), {})
    return Msg(str(value), {})


def i18n(value: object) -> dict:
    """What goes into a `<field>_i18n` key. A parameter that is a message itself is sent the same way."""
    message = of(value)
    return {"message": message.template,
            "params": {k: i18n(v) if isinstance(v, Msg) else v for k, v in message.params.items()}}


def from_i18n(data: dict) -> Msg:
    """The message behind a `<field>_i18n` value, to put it inside another one."""
    return Msg(data["message"], {k: from_i18n(v) if isinstance(v, dict) else v for k, v in data["params"].items()})


class UserError(HTTPException):
    """A refusal the dashboard shows, in the user's language."""

    def __init__(self, status: int, message: object):
        super().__init__(status, str(of(message)))
        self.i18n = i18n(message)


async def user_error_response(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, UserError)
    return JSONResponse({"detail": exc.detail, "detail_i18n": exc.i18n}, status_code=exc.status_code, headers=exc.headers)


# ------------------------------------------------------------------ general
REQUEST_TOO_LARGE = Template("The request is too large.")
NOT_CONNECTED = Template("Not connected to MyŠkoda yet. Open Settings.")
VIN_ERROR = Template("{vin}: {error}")

# ------------------------------------------------------------------ places
PLACE_NAME = Template("Name must be 1 to 60 characters.")
PLACE_KIND = Template("Kind must be home, work or place.")
PLACE_LATITUDE = Template("Latitude must be between -90 and 90.")
PLACE_LONGITUDE = Template("Longitude must be between -180 and 180.")
PLACE_RADIUS = Template("Radius must be between 20 and 5000 metres.")
PLACE_COLOUR = Template("Colour must be a hex colour such as #0b7a52.")
PLACE_PRICE_KWH = Template("Price per kWh must be between 0 and 10.")
PLACE_PRICE_MINUTE = Template("Price per minute must be between 0 and 10.")
PLACE_SESSION_FEE = Template("Session fee must be between 0 and 1000.")
PLACE_FREE_WITH_PRICE = Template("A free place cannot have a price.")
PLACE_ONE_HOME = Template("Only one home place is allowed.")
PLACE_HOME_KIND = Template("The home place cannot change its kind.")
PLACE_HOME_DELETE = Template("The home place cannot be deleted.")
PLACE_NOT_FOUND = Template("Place not found.")

# ------------------------------------------------------------------ charges, prices and settings
COST_OUT_OF_RANGE = Template("cost out of range")
CHARGE_WITHOUT_LOCATION = Template("That charge has no known location.")
CAR_POSITION_UNKNOWN = Template("The car's position is not known yet (it is moving or not reported).")
TARIFF_PRICE_RANGE = Template("{key} must be between 0 and 10 per kWh")
TARIFF_CURRENCY = Template("currency must be a short code such as EUR")
TARIFF_HOME_RADIUS = Template("home radius must be 20-5000 m")
SETTING_RANGE = Template("{key} must be between {lo} and {hi}")
SETTING_CHOICE = Template("{key} must be one of {choices}")
BATTERY_RANGE = Template("battery_kwh must be between 10 and 200")
BATTERY_NUMBER = Template("battery_kwh must be a number")

# ------------------------------------------------------------------ connection (the Settings page)
INVALID_VIN = Template("'{vin}' is not a valid VIN (17 characters, letters and digits, no I, O or Q).")
ENTER_VIN = Template("Enter at least one VIN.")
ENTER_ONE_VIN = Template("Enter exactly one VIN.")
TOO_MANY_VEHICLES = Template("At most {n} vehicles.")
DEMO_NO_ACCOUNT = Template("Demo mode: no account needed. Start without DEMO=1 to connect your car.")
CREATE_LOGIN_FIRST = Template("Create the dashboard login first.")
NOT_AN_API_KEY = Template("That does not look like an API key. Copy it completely from the MyŠkoda app.")
SPIN_DIGITS_OR_EMPTY = Template("The S-PIN is 4 digits (leave it empty if you do not use the auxiliary heater).")
SPIN_DIGITS = Template("The S-PIN is 4 digits.")
CONNECT_KEY_FIRST = Template("Connect your API key first.")
CAR_ALREADY_CONNECTED = Template("That car is already connected.")
CAR_NOT_CONNECTED = Template("That car is not connected.")
ONLY_CAR = Template("This is the only car. Use Disconnect to remove the API key.")

# ------------------------------------------------------------------ MQTT
MQTT_BROKER_ADDRESS = Template("The broker address may only contain letters, digits, dots, dashes and colons (no http:// and no spaces).")
MQTT_PORT = Template("The port must be a number between 1 and 65535.")
MQTT_PREFIX = Template("The topic prefix may only contain letters, digits, - and _ (no slashes), up to 40 characters.")
MQTT_BROKER_MISSING = Template("Enter the broker address (the IP address or name of the computer running Home Assistant's MQTT broker).")
MQTT_BROKER_FIRST = Template("Enter the broker address first.")
MQTT_PASSWORD_AGAIN = Template("Enter the password again: the broker address changed.")

# ------------------------------------------------------------------ webhooks
WEBHOOK_NO_ANSWER = Template("No answer within 10 seconds.")
WEBHOOK_NO_CONNECTION = Template("Could not connect to the receiver.")
WEBHOOK_REDIRECTED = Template("The receiver redirected. Mate does not follow redirects.")
WEBHOOK_NO_SECRET = Template("The secret cannot be read. Create a new secret.")
WEBHOOK_DISABLED = Template("The webhook was disabled.")
WEBHOOK_INTERRUPTED = Template("Mate stopped while sending.")
WEBHOOK_NAME = Template("Enter a name of 1 to 60 characters.")
WEBHOOK_URL = Template("Enter a URL that starts with http:// or https://.")
WEBHOOK_URL_LOGIN = Template("The URL must not contain a user name or password.")
WEBHOOK_EVENTS = Template("Choose at least one event.")
WEBHOOK_ENABLE_FIRST = Template("Enable the webhook first.")
WEBHOOK_ALREADY_WAITING = Template("This delivery is already waiting to be sent.")
WEBHOOK_NOT_FOUND = Template("Not found")
WEBHOOK_THRESHOLD = Template("The low-battery threshold must be a whole number from 5 to 50.")

# ------------------------------------------------------------------ activity, trips, import, data quality
BAD_DATE = Template("bad date '{day}', expected YYYY-MM-DD")
RANGE_REVERSED = Template("The start must be before the end.")
RANGE_LIMIT_31 = Template("The range is limited to 31 days.")
RANGE_ENDS_EARLY = Template("The range ends before it starts.")
MIN_HOURS_RANGE = Template("min_hours must be between 1 and 168.")
MIN_HOURS_POSITIVE = Template("min_hours must be greater than 0.")
MERGE_COUNT = Template("Choose between 2 and {n} trips.")
MERGE_MISSING = Template("One of the trips does not exist.")
MERGE_RUNNING = Template("A trip that is still running cannot be merged.")
MERGE_OVERLAP = Template("These trips overlap in time.")
MERGE_GAP = Template("These trips are more than {hours} hours apart: that was a separate trip.")
MERGE_NOT_MERGED = Template("This trip was not merged.")
IMPORT_TOO_MANY_FILES = Template("At most {n} files at once.")
IMPORT_TOO_LARGE = Template("The files are too large (limit 8 MB in total).")
IMPORT_NO_FILE = Template("Choose at least one CSV file.")
IMPORT_TIME_ZONE = Template("Unknown time zone '{name}'. Use a name like Europe/Berlin.")

# ------------------------------------------------------------------ commands
CMD_REQUIRED = Template("'{key}' is required")
CMD_NUMBER = Template("'{key}' must be a number")
CMD_RANGE = Template("'{key}' must be between {lo} and {hi}")
CMD_UNKNOWN = Template("unknown command '{name}'")
CMD_UNKNOWN_VEHICLE = Template("Unknown vehicle")
CMD_NOT_SUPPORTED = Template("This car does not support that operation.")
CMD_CHARGE_MODE = Template("'mode' must be one of {choices}")
CMD_NEEDS_SPIN = Template("The auxiliary heater needs your S-PIN. Add it under Settings.")
CMD_AUX_MODE = Template("'mode' must be HEATING or VENTILATION")
CMD_PROFILE_REQUIRED = Template("'profile_id' is required")
CMD_PROFILE_INTEGER = Template("'profile_id' must be an integer")
CMD_PROFILE_UNKNOWN = Template("Unknown charging profile; refresh the data first.")
CMD_NAME_EMPTY = Template("'name' must not be empty")
CMD_MAX_CURRENT = Template("'max_current' must be REDUCED or MAXIMUM")
CMD_AUTO_UNLOCK = Template("'auto_unlock' must be PERMANENT or OFF")
CMD_CHARGING_TIMES = Template("charging times need start and end as HH:mm")
CMD_TIMER_TIME = Template("timer time must be HH:mm")
CMD_TIMER_TYPE = Template("timer type must be ONE_OFF or RECURRING")
CMD_TIMER_DAYS = Template("timer days must be MONDAY..SUNDAY")
CMD_ONE_OFF_DAY = Template("one_off_day must be MONDAY..SUNDAY")
CMD_BUDGET = Template("Škoda's request limit is used up; try again in {minutes} min.")

# ------------------------------------------------------------------ Škoda's answers and the poller
API_KEY_EXPIRED = Template("The API key has expired. Create a new one in the MyŠkoda app and enter it under Settings.")
API_KEY_NOT_AUTHORIZED = Template("This API key is not allowed to access that vehicle. Check the key's vehicles in the MyŠkoda app.")
API_OPERATION_NOT_AUTHORIZED = Template("The car refused the operation for the user this key belongs to.")
API_OPERATION_DISABLED = Template("That feature is currently disabled for the car (consent, licence or workshop mode).")
API_RATE_LIMIT = Template("Škoda's request limit is used up. Mate waits for it to reset.")
API_VEHICLE_BUSY = Template("The car declined the request (it limits how often it acts, or its battery is low). Try again later.")
API_TIMEOUT = Template("The request timed out.")
API_REJECTED_KEY = Template("Škoda rejected the API key (401). Check that it was copied completely.")
API_NO_VEHICLE = Template("No vehicle with that VIN is reachable with this key.")
API_ERROR = Template("Škoda API error {status}")
API_ERROR_DETAIL = Template("Škoda API error {status}: {detail}")
BUDGET_NEXT_SLOT = Template("Request limit reached; next slot in {seconds} s")

# ------------------------------------------------------------------ MQTT connection
MQTT_CONNECTED = Template("Connected to the broker.")
MQTT_REFUSED = Template("The broker refused the user name or password. Check both (in Home Assistant: the user must exist and be allowed to use MQTT).")
MQTT_CONNECTION_LOST = Template("Connection lost: {reason}")
MQTT_UNREACHABLE = Template("Cannot reach {host}:{port}.")
MQTT_UNREACHABLE_HELP = Template("Cannot reach {host}:{port}. Is the broker running, is the address right, and can Mate's computer or container reach it?")
MQTT_NO_ANSWER = Template("No answer from {host}:{port} within {seconds} s.")
MQTT_SETUP_FAILED = Template("Could not set up the connection: {error}")
MQTT_CONNECT_FAILED = Template("Could not connect: {error}")

# ------------------------------------------------------------------ import report
IMPORT_EMPTY = Template("The file is empty.")
IMPORT_NOT_AN_EXPORT = Template("This does not look like a MyŠkoda trip export: missing column(s) {columns}. Found: {found}…")
IMPORT_BAD_DATE = Template("line {line}: unreadable date '{start}' / '{end}'")
IMPORT_ENDS_EARLY = Template("line {line}: the trip ends before it starts")
IMPORT_OTHER_CAR = Template("This export belongs to another car ({vin}), not this one. It was skipped.")

# ------------------------------------------------------------------ data quality
QUALITY_UNKNOWN_ACTION = Template("Unknown action.")
QUALITY_UNKNOWN_CHECK = Template("Unknown check.")

TEMPLATES: tuple[Template, ...] = tuple(value for value in list(globals().values()) if isinstance(value, Template))
