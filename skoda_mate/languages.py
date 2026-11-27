"""The dashboard's languages: the one list the settings API accepts and the Settings picker shows.

A language is added here only when its catalog (static/i18n/<code>.json, registered in static/i18n.js) is complete.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Language:
    code: str    # what is stored in the settings and names the catalog file
    name: str    # in the language itself, as the picker shows it
    locale: str  # BCP 47: for Intl and the page's lang attribute


LANGUAGES = (
    Language("en", "English", "en"),
    Language("de", "Deutsch", "de"),
    Language("da", "Dansk", "da"),
    Language("nl", "Nederlands", "nl"),
    Language("nb", "Norsk bokmål", "nb"),
    Language("fi", "Suomi", "fi"),
    Language("sv", "Svenska", "sv"),
)
BY_CODE = {language.code: language for language in LANGUAGES}
DEFAULT = BY_CODE["en"]
