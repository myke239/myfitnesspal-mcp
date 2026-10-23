"""Bounded reads and JSON normalization, independent of MCP transport."""

import configparser
import math
import os
import re
import sys
import time
from datetime import date, datetime, timedelta
from http.cookiejar import MozillaCookieJar
from pathlib import Path
from zoneinfo import ZoneInfo


def local_today():
    """Resolve omitted SDK dates in the explicitly configured user timezone."""
    return datetime.now(
        ZoneInfo(os.environ.get("MFP_TIMEZONE", "America/Los_Angeles"))
    ).date()


def page(items, cursor=0, limit=100):
    if (
        isinstance(cursor, bool)
        or isinstance(limit, bool)
        or cursor < 0
        or not 1 <= limit <= 100
    ):
        raise ValueError("Use cursor >= 0 and limit 1–100")
    return {
        "items": items[cursor : cursor + limit],
        "total": len(items),
        "next_cursor": cursor + limit if cursor + limit < len(items) else None,
    }


class AccessError(RuntimeError):
    """Sanitized upstream failure safe to return to a tool caller."""


def _browser_cookie_profiles(browser: str) -> list[Path]:
    """Find cookie databases from every installed browser profile on Windows.

    browser-cookie3's default Firefox lookup selects one profile only. People
    commonly keep MyFitnessPal signed in on a non-default profile, so include
    all profiles and let the upstream verifier decide which session works.
    """
    if sys.platform != "win32":
        return []
    roaming = Path(os.environ.get("APPDATA", ""))
    local = Path(os.environ.get("LOCALAPPDATA", ""))
    if browser == "firefox":
        firefox_root = roaming / "Mozilla" / "Firefox"
        profile_dirs = list((firefox_root / "Profiles").glob("*"))
        profiles_ini = firefox_root / "profiles.ini"
        if profiles_ini.is_file():
            profiles = configparser.ConfigParser()
            profiles.read(profiles_ini, encoding="utf-8")
            for section in profiles.sections():
                if not section.startswith("Profile"):
                    continue
                profile_path = profiles[section].get("Path")
                if not profile_path:
                    continue
                path = Path(profile_path)
                if profiles[section].getboolean("IsRelative", fallback=True):
                    path = firefox_root / path
                profile_dirs.append(path)
        return list(
            dict.fromkeys(
                cookie_db
                for profile in profile_dirs
                for cookie_db in [profile / "cookies.sqlite"]
                if cookie_db.is_file()
            )
        )
    vendor = {"chrome": "Google\\Chrome", "edge": "Microsoft\\Edge"}.get(browser)
    if not vendor:
        return []
    user_data = local / vendor / "User Data"
    if not user_data.is_dir():
        return []
    return [
        p
        for profile in user_data.iterdir()
        if profile.is_dir()
        for p in (profile / "Network" / "Cookies", profile / "Cookies")
        if p.is_file()
    ]


def _load_browser_cookies(loader, browser: str, domain: str):
    """Load cookies from all available Windows profiles, with a normal fallback."""
    profiles = _browser_cookie_profiles(browser)
    if not profiles:
        return loader(domain_name=domain)
    combined = None
    errors = []
    for profile in profiles:
        try:
            jar = loader(cookie_file=str(profile), domain_name=domain)
            if combined is None:
                combined = jar
            else:
                for cookie in jar:
                    combined.set_cookie(cookie)
        except Exception as error:
            errors.append(error)
    if combined is not None:
        return combined
    if errors:
        raise errors[0]
    return loader(domain_name=domain)


def parse_date(value: str) -> date:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("Use an explicit YYYY-MM-DD date.")
    return date.fromisoformat(value)


def date_range(start: str, end: str) -> list[date]:
    first, last = parse_date(start), parse_date(end)
    count = (last - first).days + 1
    if not 1 <= count <= 31:
        raise ValueError("Use an inclusive range of 1 to 31 days.")
    return [first + timedelta(days=i) for i in range(count)]


def nutrition(values: dict) -> dict:
    result = {}
    for key, value in values.items():
        result[key] = (
            float(value)
            if isinstance(value, (int, float)) and math.isfinite(value)
            else None
        )
    return result


def create_client():
    """Load only explicit cookies or a single selected browser's MFP cookies."""
    import browser_cookie3
    import myfitnesspal

    cookie_file = os.environ.get("MFP_COOKIE_FILE")
    if cookie_file:
        jar = MozillaCookieJar(cookie_file)
        jar.load(ignore_discard=True, ignore_expires=False)
        for cookie in list(jar):
            if cookie.domain.lstrip(".") not in (
                "myfitnesspal.com",
                "www.myfitnesspal.com",
            ):
                jar.clear(cookie.domain, cookie.path, cookie.name)
    else:
        browser = os.environ.get("MFP_BROWSER", "chrome").lower()
        loaders = {
            "chrome": browser_cookie3.chrome,
            "edge": browser_cookie3.edge,
            "firefox": browser_cookie3.firefox,
        }
        if browser not in loaders:
            raise ValueError("MFP_BROWSER must be chrome, edge, or firefox.")
        try:
            jar = _load_browser_cookies(
                loaders[browser], browser, "myfitnesspal.com"
            )
        except Exception as error:
            if type(error).__name__ == "RequiresAdminError":
                raise AccessError(
                    f"Cannot read {browser} cookies: the cookie loader requested "
                    "administrator access. Try a signed-in Firefox session with "
                    "verify --browser firefox, or set MFP_BROWSER=firefox for "
                    "the MCP server."
                ) from None
            raise AccessError(
                f"Cannot read {browser} cookies. Check the selected browser's "
                "local profile or use MFP_COOKIE_FILE. No MyFitnessPal request "
                "was made."
            ) from None

    # The library authenticates in its constructor. Install bounded requests
    # before that happens; never enable upstream request logging.
    class BoundedClient(myfitnesspal.Client):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            original = self.session.request

            def request(method, url, **kwargs):
                deadline = getattr(self, "operation_deadline", time.monotonic() + 90)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("SDK operation request budget exhausted")
                kwargs["timeout"] = (min(10, remaining), min(30, remaining))
                return original(method, url, **kwargs)

            self.session.request = request

        def _get_request_for_url(self, *args, **kwargs):
            kwargs.setdefault("timeout", (10, 30))
            return super()._get_request_for_url(*args, **kwargs)

    return BoundedClient(cookiejar=jar, unit_aware=False)


class Service:
    def __init__(self, client_factory=create_client, today=local_today):
        self.client_factory = client_factory
        self._client = None
        self.today = today

    def call(self, operation):
        try:
            if self._client is None:
                self._client = self.client_factory()
            self._client.operation_deadline = time.monotonic() + 90
            return operation(self._client)
        except AccessError:
            self._client = None
            raise
        except Exception as error:
            self._client = None
            if type(error).__name__ == "MyfitnesspalLoginError":
                raise AccessError(
                    "MyFitnessPal rejected the cookies found in the selected "
                    "browser profiles. Check that the signed-in profile is the "
                    "one opened by the installer, then try again."
                ) from None
            status_code = getattr(error, "status_code", None)
            if status_code is None and type(error).__name__ == "MyfitnesspalRequestFailed":
                match = re.search(r"status code:\s*(\d{3})", str(error), re.IGNORECASE)
                status_code = int(match.group(1)) if match else None
            if status_code == 403:
                raise AccessError(
                    "MyFitnessPal returned HTTP 403 while checking the browser "
                    "session. The cookies were read, but MyFitnessPal denied "
                    "the request; switching browsers may not resolve this."
                ) from None
            raise AccessError(
                "MyFitnessPal access failed while checking the selected browser "
                "profiles. Confirm the browser profile is signed in and try "
                "again. No account change was attempted."
            ) from None

    def connection_status(self):
        return self.call(
            lambda c: {
                "connected": True,
                "username": c.effective_username,
                "writes_supported": True,
                "live_writes_verified": False,
            }
        )

    def food_search(self, query: str, limit: int = 20):
        if not query.strip() or len(query) > 200 or not 1 <= limit <= 100:
            raise ValueError(
                "Use a nonempty query up to 200 characters and limit 1–100"
            )
        return self.call(
            lambda c: {
                "foods": [
                    {
                        "food_id": str(f.mfp_id),
                        "name": f.name,
                        "brand": f.brand,
                        "calories": f.calories,
                        "verified": f.verified,
                    }
                    for f in c.get_food_search_results(query)[:limit]
                ]
            }
        )

    def food_details(self, food_id: str):
        from .operations import Api, FoodId, food_item

        FoodId(food_id=food_id)

        def read(c):
            food = food_item(Api(c), food_id)
            # Keep the existing raw API fields and add the complete SDK projection.
            sizes = food.get("serving_sizes", [])
            nutrients = food.get("nutritional_contents", {})
            food["sdk"] = {
                "mfp_id": food.get("id"),
                "name": food.get("description"),
                "brand": food.get("brand_name"),
                "verified": food.get("verified"),
                "details": nutrients,
                "calories": nutrients.get("energy", {}).get("value"),
                "confirmations": food.get("confirmations"),
                "serving": next(
                    (s.get("unit") for s in sizes if s.get("index") == 0), None
                ),
                "servings": [{**s, "serving_id": s.get("id")} for s in sizes],
            }
            return food

        return self.call(read)

    def recipes(self, cursor=0, limit=100):
        page([], cursor, limit)
        return self.call(
            lambda c: page(
                [{"recipe_id": str(k), "title": v} for k, v in c.get_recipes().items()],
                cursor,
                limit,
            )
        )

    def recipe(self, recipe_id):
        from .operations import FoodId

        FoodId(food_id=recipe_id)
        return self.call(lambda c: c.get_recipe(int(recipe_id)))

    def saved_meals(self, cursor=0, limit=100):
        page([], cursor, limit)
        return self.call(
            lambda c: page(
                [{"meal_id": str(k), "title": v} for k, v in c.get_meals().items()],
                cursor,
                limit,
            )
        )

    def saved_meal(self, meal_id):
        from .operations import FoodId

        FoodId(food_id=meal_id)

        def read(c):
            meals = {str(k): v for k, v in c.get_meals().items()}
            if meal_id not in meals:
                raise AccessError("Saved meal not found in the signed-in account.")
            return c.get_meal(int(meal_id), meals[meal_id])

        return self.call(read)

    def report(
        self,
        report_name="Net Calories",
        report_category="Nutrition",
        start_date=None,
        end_date=None,
    ):
        for name in (report_name, report_category):
            if not isinstance(name, str) or not re.fullmatch(
                r"[A-Za-z0-9 _%-]{1,100}", name
            ):
                raise ValueError(
                    "Use a report name/category without URL path or query characters"
                )
        last = parse_date(end_date) if end_date else self.today()
        first = parse_date(start_date) if start_date else last - timedelta(days=30)
        if first > last:
            first, last = last, first  # SDK-compatible bound ordering.
        if (last - first).days > 365:
            raise ValueError("Report requests are limited to 366 inclusive days")

        def read(c):
            values = c.get_report(
                report_name=report_name,
                report_category=report_category,
                lower_bound=first,
                upper_bound=last,
            )
            return {
                "report_name": report_name,
                "report_category": report_category,
                "start_date": first.isoformat(),
                "end_date": last.isoformat(),
                "entries": [
                    {"date": d.isoformat(), "value": v}
                    for d, v in sorted(values.items())
                ],
                "units": None,
                "coverage": "available SDK report observations only",
                "warnings": (
                    [
                        "SDK warns that report history older than 80 days may be inaccurate."
                    ]
                    if (self.today() - first).days > 80
                    else []
                )
                + (
                    [
                        "SDK report labels are reconstructed using the host date; host and user dates differ."
                    ]
                    if date.today() != self.today()
                    else []
                ),
            }

        return self.call(read)

    def account_data(
        self, resource, calendar_date=None, query="", item_id=None, limit=100
    ):
        from .operations import Api, FoodId

        if not 1 <= limit <= 100 or len(query) > 200:
            raise ValueError("Use limit 1–100 and query up to 200 characters")
        paths = {
            "diary_entries": "/api/services/diary/read_diary",
            "nutrition_goals": "/api/services/nutrient-goals",
            "custom_foods": "/api/services/users/foods/mine",
            "measurements": "/api/user-measurements/measurements",
            "measurement_types": "/api/user-measurements/measurements/types",
            "saved_meals": "/api/services/users/meals/mine",
            "diary_notes": "/api/services/diary/read_notes",
            "exercise_search": "/api/services/exercises/search",
        }
        if resource not in {
            *paths,
            "recipes",
            "recipe",
            "saved_meal",
            "account_preferences",
        }:
            raise ValueError("Unsupported read resource")
        params = {}
        if resource in ("diary_entries", "diary_notes"):
            parse_date(calendar_date or "")
            params["date"] = calendar_date
        if resource == "diary_notes":
            params["note_type"] = "food"
        if resource in ("custom_foods", "exercise_search"):
            params["search"] = query
        if resource in ("recipe", "saved_meal"):
            FoodId(food_id=item_id)

        def read(c):
            if resource == "account_preferences":
                return {
                    "meal_names": c.user_metadata["diary_preferences"]["meal_names"],
                    "units": c.user_metadata["unit_preferences"],
                }
            if resource == "recipes":
                return dict(list(c.get_recipes().items())[:limit])
            if resource == "recipe":
                return c.get_recipe(int(item_id))
            if resource == "saved_meal":
                meals = c.get_meals()
                title = meals.get(item_id, meals.get(int(item_id)))
                if title is None:
                    raise ValueError("Saved meal not found")
                return c.get_meal(int(item_id), title)
            data = Api(c).request("GET", paths[resource], params=params)
            if isinstance(data, list):
                return {
                    "items": data[:limit],
                    "returned": min(limit, len(data)),
                    "truncated": len(data) > limit,
                }
            return data

        return self.call(read)

    def diary(
        self,
        calendar_date: str,
        username=None,
        friend_username=None,
        include_notes=True,
    ):
        selected = parse_date(calendar_date)
        for user in (username, friend_username):
            if user is not None and not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", user):
                raise ValueError("Invalid diary username")

        def read(client):
            options = {
                k: v
                for k, v in {
                    "username": username,
                    "friend_username": friend_username,
                }.items()
                if v is not None
            }
            day = client.get_date(selected, **options)
            other_user = (
                friend_username or username or client.effective_username
            ) != client.effective_username
            notes = None
            notes_status = "not_requested"
            if include_notes and not other_user and friend_username is None:
                try:
                    note = getattr(day, "notes", "")
                    notes = (
                        note.as_dict()
                        if hasattr(note, "as_dict")
                        else {"body": str(note)}
                    )
                    notes_status = "available"
                except Exception:
                    notes_status = "unavailable"
            elif other_user or friend_username is not None:
                notes_status = "not_available_for_alternate_diary"
            return {
                "date": selected.isoformat(),
                "complete": day.complete,
                "totals": nutrition(day.totals),
                "goals": nutrition(day.goals),
                "notes": notes,
                "notes_status": notes_status,
                "diary_username": friend_username
                or username
                or client.effective_username,
                "meals": [
                    {
                        "name": m.name,
                        "totals": nutrition(getattr(m, "totals", {})),
                        "entries": [
                            {
                                "name": e.name,
                                "nutrition": nutrition(e.nutrition_information),
                                "short_name": getattr(e, "short_name", None),
                                "quantity": getattr(e, "quantity", None),
                                "unit": getattr(e, "unit", None),
                                "quantity_source": "SDK parsing of entry name; may be unavailable",
                            }
                            for e in m.entries
                        ],
                    }
                    for m in day.meals
                ],
                "coverage": "logged entries only; empty diary may indicate an upstream parsing change",
            }

        return self.call(read)

    def summary(self, start_date: str, end_date: str):
        dates = date_range(start_date, end_date)
        days = [self.diary(d.isoformat()) for d in dates]
        keys = set().union(*(d["totals"] for d in days))
        averages = {}
        coverage = {}
        for key in sorted(keys):
            values = [
                d["totals"][key] for d in days if d["totals"].get(key) is not None
            ]
            averages[key] = sum(values) / len(values) if values else None
            coverage[key] = len(values)
        return {
            "start_date": start_date,
            "end_date": end_date,
            "days": days,
            "daily_averages": averages,
            "days_with_each_nutrient": coverage,
            "requested_days": len(dates),
        }

    def water(self, calendar_date: str):
        selected = parse_date(calendar_date)
        return self.call(
            lambda c: {"date": calendar_date, "water_ml": c.get_date(selected).water}
        )

    def exercises(self, calendar_date: str, friend_username=None):
        selected = parse_date(calendar_date)
        if friend_username is not None and not re.fullmatch(
            r"[A-Za-z0-9_.-]{1,100}", friend_username
        ):
            raise ValueError("Invalid friend username")
        return self.call(
            lambda c: {
                "date": calendar_date,
                "groups": [
                    {
                        "name": group.name,
                        "entries": [
                            {
                                "name": e.name,
                                "raw_metrics": nutrition(e.nutrition_information),
                            }
                            for e in group.entries
                        ],
                    }
                    for group in (
                        c.get_date(selected, friend_username=friend_username)
                        if friend_username is not None
                        else c.get_date(selected)
                    ).exercises
                ],
                "units": "upstream raw metrics; do not infer unspecified units",
            }
        )

    def measurements(self, measurement="Weight", start_date=None, end_date=None):
        last = parse_date(end_date) if end_date else self.today()
        first = parse_date(start_date) if start_date else last - timedelta(days=30)
        if first > last:
            first, last = last, first
        if (last - first).days > 365:
            raise ValueError("Measurement requests are limited to 366 inclusive days")
        if not measurement.strip() or len(measurement) > 100:
            raise ValueError("Provide a measurement name of 1 to 100 characters.")
        return self.call(
            lambda c: {
                "measurement": measurement,
                "unit": None,
                "unit_note": "numeric account values; units not verified",
                "start_date": first.isoformat(),
                "end_date": last.isoformat(),
                "entries": [
                    {"date": d.isoformat(), "value": v}
                    for d, v in sorted(
                        c.get_measurements(
                            measurement, lower_bound=first, upper_bound=last
                        ).items()
                    )
                ],
            }
        )
