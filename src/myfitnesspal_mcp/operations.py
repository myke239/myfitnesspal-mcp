"""Explicit MyFitnessPal read/write contracts and fixed upstream routes.

Web endpoint shapes researched from the implementations attributed in
THIRD_PARTY_NOTICES.md. No caller-selected URLs or arbitrary API operations.
"""

import copy
import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .service import parse_date
from .storage import TokenStore, data_directory, session_lock


class Input(BaseModel):
    model_config = ConfigDict(
        extra="forbid", allow_inf_nan=False, str_strip_whitespace=True, strict=True
    )


class Dated(Input):
    calendar_date: str

    @model_validator(mode="after")
    def valid_date(self):
        parse_date(self.calendar_date)
        return self


class EntryId(Input):
    entry_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,100}$")


class FoodId(Input):
    food_id: str = Field(pattern=r"^[0-9]{1,30}$")


class AddFood(Dated, FoodId):
    meal_name: str = Field(min_length=1, max_length=100)
    servings: float = Field(gt=0, le=10000)
    serving_index: int = Field(
        ge=0, le=1000, description="Exact index returned by get_food_details."
    )


class UpdateFood(EntryId):
    servings: float | None = Field(default=None, gt=0, le=10000)
    meal_name: str | None = Field(default=None, min_length=1, max_length=100)

    @model_validator(mode="after")
    def changed(self):
        if self.servings is None and self.meal_name is None:
            raise ValueError("Provide servings or meal_name")
        return self


class Water(Dated):
    milliliters: float = Field(
        ge=0, le=100000, description="Replace the day's TOTAL water, not an increment."
    )


class Measurement(Dated):
    measurement: str = Field(min_length=1, max_length=100)
    value: float = Field(ge=0, le=1000000)
    unit: str = Field(
        min_length=1,
        max_length=30,
        description="Explicit unit, for example kg or lbs. Never infer.",
    )


class Goals(Dated):
    calories: float = Field(gt=0, le=100000)
    carbohydrates: float = Field(ge=0, le=10000, description="Daily grams")
    protein: float = Field(ge=0, le=10000, description="Daily grams")
    fat: float = Field(ge=0, le=10000, description="Daily grams")


class SdkGoal(Input):
    energy: float = Field(ge=0, le=100000)
    energy_unit: Literal["calories", "kilojoules", "account"] = "calories"
    carbohydrates: float | None = Field(default=None, ge=0, le=10000)
    protein: float | None = Field(default=None, ge=0, le=10000)
    fat: float | None = Field(default=None, ge=0, le=10000)
    percent_carbohydrates: float | None = Field(default=None, ge=0, le=100)
    percent_protein: float | None = Field(default=None, ge=0, le=100)
    percent_fat: float | None = Field(default=None, ge=0, le=100)
    calendar_date: str | None = None

    @model_validator(mode="after")
    def mode(self):
        absolute = [self.carbohydrates, self.protein, self.fat]
        percent = [self.percent_carbohydrates, self.percent_protein, self.percent_fat]
        if any(v is not None for v in absolute) and any(v is not None for v in percent):
            raise ValueError("Use absolute macros or percentages, not both")
        for values in (absolute, percent):
            if any(v is not None for v in values) and not all(
                v is not None for v in values
            ):
                raise ValueError("Supply all three macros in the chosen mode")
        if all(v is not None for v in percent) and abs(sum(percent) - 100) > 1e-6:
            raise ValueError("Macro percentages must sum to 100")
        if self.energy == 0 and (self.carbohydrates is None or sum(absolute) == 0):
            raise ValueError(
                "Energy must be positive unless positive absolute macros determine it"
            )
        if self.calendar_date is not None:
            parse_date(self.calendar_date)
        return self


class SdkMeasurement(Input):
    measurement: str = Field(default="Weight", min_length=1, max_length=100)
    value: float = Field(ge=0, le=1000000)
    calendar_date: str | None = None
    unit: str | None = Field(default=None, min_length=1, max_length=30)

    @model_validator(mode="after")
    def dated(self):
        if self.calendar_date is not None:
            parse_date(self.calendar_date)
        return self


class Nutrients(Input):
    calories: float = Field(ge=0, le=100000)
    carbohydrates: float = Field(
        ge=0,
        le=10000,
        description="Total carbohydrate grams including fiber (US label).",
    )
    protein: float = Field(ge=0, le=10000)
    fat: float = Field(ge=0, le=10000)
    fiber: float | None = Field(default=None, ge=0, le=10000)
    sugar: float | None = Field(default=None, ge=0, le=10000)
    sodium: float | None = Field(default=None, ge=0, le=1000000, description="mg")
    potassium: float | None = Field(default=None, ge=0, le=1000000, description="mg")
    cholesterol: float | None = Field(default=None, ge=0, le=1000000, description="mg")
    saturated_fat: float | None = Field(default=None, ge=0, le=10000)
    monounsaturated_fat: float | None = Field(default=None, ge=0, le=10000)
    polyunsaturated_fat: float | None = Field(default=None, ge=0, le=10000)
    trans_fat: float | None = Field(default=None, ge=0, le=10000)
    vitamin_a: float | None = Field(default=None, ge=0, le=100000, description="%DV")
    vitamin_c: float | None = Field(default=None, ge=0, le=100000, description="%DV")
    calcium: float | None = Field(default=None, ge=0, le=100000, description="%DV")
    iron: float | None = Field(default=None, ge=0, le=100000, description="%DV")


class CustomFood(Input):
    description: str = Field(min_length=1, max_length=200)
    brand_name: str = Field(default="Generic", min_length=1, max_length=200)
    serving_amount: float = Field(gt=0, le=100000)
    serving_unit: str = Field(min_length=1, max_length=100)
    nutrients: Nutrients
    public: bool = False
    servings_per_container: float = Field(default=1, gt=0, le=100000)


class SdkFood(Input):
    brand: str = Field(max_length=200)
    description: str = Field(min_length=1, max_length=200)
    calories: int = Field(ge=0, le=100000)
    fat: float = Field(ge=0, le=10000)
    carbs: float = Field(ge=0, le=10000)
    protein: float = Field(ge=0, le=10000)
    sodium: float | None = Field(default=None, ge=0, le=1000000)
    potassium: float | None = Field(default=None, ge=0, le=1000000)
    saturated_fat: float | None = Field(default=None, ge=0, le=10000)
    polyunsaturated_fat: float | None = Field(default=None, ge=0, le=10000)
    fiber: float | None = Field(default=None, ge=0, le=10000)
    monounsaturated_fat: float | None = Field(default=None, ge=0, le=10000)
    sugar: float | None = Field(default=None, ge=0, le=10000)
    trans_fat: float | None = Field(default=None, ge=0, le=10000)
    cholesterol: float | None = Field(default=None, ge=0, le=1000000)
    vitamin_a: float | None = Field(default=None, ge=0, le=100000)
    calcium: float | None = Field(default=None, ge=0, le=100000)
    vitamin_c: float | None = Field(default=None, ge=0, le=100000)
    iron: float | None = Field(default=None, ge=0, le=100000)
    serving_size: str = Field(default="1 Serving", min_length=1, max_length=100)
    servingspercontainer: float = Field(default=1, gt=0, le=100000)
    sharepublic: bool = False


class EditCustomFood(CustomFood, FoodId):
    pass


class Fast(EntryId):
    fast_started: str = Field(description="ISO 8601 timestamp with explicit timezone.")
    fast_ended: str = Field(description="ISO 8601 timestamp with explicit timezone.")

    @model_validator(mode="after")
    def timestamps(self):
        UUID(self.entry_id)
        values = []
        for field in ("fast_started", "fast_ended"):
            value = datetime.fromisoformat(getattr(self, field).replace("Z", "+00:00"))
            if value.tzinfo is None:
                raise ValueError("Timestamps require an explicit timezone")
            value = value.astimezone(timezone.utc).replace(microsecond=0)
            setattr(self, field, value.isoformat().replace("+00:00", "Z"))
            values.append(value)
        if values[1] <= values[0]:
            raise ValueError("Fast end must be after start")
        return self


WriteOperation = Literal[
    "add_food_to_diary",
    "update_food_diary_entry",
    "delete_food_diary_entry",
    "set_water",
    "set_measurement",
    "delete_measurement",
    "set_nutrition_goals",
    "create_custom_food",
    "update_custom_food",
    "delete_custom_food",
    "log_fast",
    "update_fast",
    "delete_fast",
    "sdk_set_measurements",
    "sdk_set_new_food",
    "sdk_set_new_goal",
]
MODELS = {
    "add_food_to_diary": AddFood,
    "update_food_diary_entry": UpdateFood,
    "delete_food_diary_entry": EntryId,
    "set_water": Water,
    "set_measurement": Measurement,
    "delete_measurement": EntryId,
    "set_nutrition_goals": Goals,
    "create_custom_food": CustomFood,
    "update_custom_food": EditCustomFood,
    "delete_custom_food": FoodId,
    "log_fast": Fast,
    "update_fast": Fast,
    "delete_fast": EntryId,
    "sdk_set_measurements": SdkMeasurement,
    "sdk_set_new_food": SdkFood,
    "sdk_set_new_goal": SdkGoal,
}


class UpstreamFailure(Exception):
    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code


class Api:
    def __init__(self, client):
        self.client = client
        self.write_sent = False
        self.stage = "preflight"

    def request(self, method, path, payload=None, params=None, v2=False):
        self.stage = (
            "meal_lookup" if path.endswith("/diary/profile")
            else "food_lookup" if path.startswith("/v2/foods/") and method == "GET"
            else "target_lookup" if method == "GET" else "submission"
        )
        base = "https://api.myfitnesspal.com" if v2 else "https://www.myfitnesspal.com"
        headers = {"Accept": "application/json"}
        if v2:
            headers.update(
                {
                    "Authorization": "Bearer " + self.client.access_token,
                    "mfp-client-id": "mfp-main-js",
                    "mfp-user-id": str(self.client.user_id),
                }
            )
        elif method != "GET":
            response = self.client.session.get(
                base + "/api/auth/csrf",
                timeout=(10, 30),
                allow_redirects=False,
                headers=headers,
            )
            if response.status_code != 200:
                raise UpstreamFailure("CSRF discovery failed before the write")
            token = response.json().get("csrfToken")
            if not token:
                raise UpstreamFailure("CSRF token missing before the write")
            headers["x-csrf-token"] = token
        if method != "GET":
            self.write_sent = True
        response = self.client.session.request(
            method,
            base + path,
            json=payload,
            params=params,
            headers=headers,
            timeout=(10, 30),
            allow_redirects=False,
        )
        if not 200 <= response.status_code < 300:
            raise UpstreamFailure(
                f"MyFitnessPal returned HTTP {response.status_code}", response.status_code
            )
        if response.status_code == 204 or not response.content:
            return None
        return response.json()


def food_item(api, food_id):
    result = api.request(
        "GET",
        "/v2/foods/" + food_id,
        params={"fields[]": ["nutritional_contents", "serving_sizes", "confirmations"]},
        v2=True,
    )
    item = result.get("item", {})
    if str(item.get("id")) != str(food_id):
        raise UpstreamFailure("Food lookup did not return the exact requested ID")
    return item


def custom_payload(p):
    nutrients = p.nutrients.model_dump(exclude_none=True)
    calories = nutrients.pop("calories")
    # US convention: carbohydrates already include fiber; omit EU country overrides.
    return {
        "description": p.description,
        "brand_name": p.brand_name,
        "type": "food",
        "public": p.public,
        "nutritional_contents": {
            **nutrients,
            "energy": {"unit": "calories", "value": calories},
            "grams": 1,
        },
        "serving_sizes": [
            {
                "value": p.serving_amount,
                "unit": p.serving_unit,
                "nutrition_multiplier": 1,
                "gram_weight": 1,
                "fraction": False,
                "index": 0,
            },
            {
                "value": 1,
                "unit": f"container ({p.servings_per_container} servings)",
                "nutrition_multiplier": p.servings_per_container,
                "gram_weight": 1,
                "fraction": False,
                "index": 1,
            },
        ],
    }


def resolve_goal(p, previous, unit):
    """SDK 2.1.2 energy/macro calculations, without mutating session headers."""
    if unit not in ("calories", "kilojoules"):
        raise ValueError("Unsupported account energy unit")
    energy = p.energy
    names = ("carbohydrates", "protein", "fat")
    if p.carbohydrates is not None:
        macros = {k: getattr(p, k) for k in names}
        calculated = (
            macros["carbohydrates"] * 4 + macros["protein"] * 4 + macros["fat"] * 9
        )
        energy = max(energy, calculated * (4.184 if unit == "kilojoules" else 1))
        return energy, macros, "absolute_macros"
    if p.percent_carbohydrates is not None:
        macros = {
            k: energy * getattr(p, "percent_" + k) / 100 / factor
            for k, factor in zip(names, (4, 4, 9))
        }
        if unit == "kilojoules":
            macros = {k: round(v / 4.184, 2) for k, v in macros.items()}
        return energy, macros, "percentage_macros"
    old_energy = float(previous["energy"]["value"])
    old_unit = previous["energy"]["unit"]
    if old_unit not in ("calories", "kilojoules") or old_energy <= 0:
        raise ValueError("Previous goal has invalid energy or units")
    if old_unit != unit:
        old_energy *= 0.2388 if old_unit == "kilojoules" else 4.184
    return (
        energy,
        {k: energy * float(previous[k]) / old_energy for k in names},
        "preserve_macro_proportions",
    )


def apply_operation(api, operation, p):
    web = "/api/services"
    if operation == "sdk_set_new_food":
        values = p.model_dump(exclude_none=True)
        for key in (
            "brand",
            "description",
            "serving_size",
            "servingspercontainer",
            "sharepublic",
        ):
            values.pop(key, None)
        values["carbohydrates"] = values.pop("carbs")
        food = CustomFood(
            description=p.description,
            brand_name=p.brand or "Generic",
            serving_amount=1,
            serving_unit=p.serving_size,
            servings_per_container=p.servingspercontainer,
            public=p.sharepublic,
            nutrients=Nutrients(**values),
        )
        return api.request("POST", web + "/foods", {"item": custom_payload(food)})
    if operation == "sdk_set_measurements":
        if p.unit is None:
            if p.measurement != "Weight":
                raise ValueError("Non-weight measurements require an explicit unit")
            p.unit = api.client.user_metadata["unit_preferences"]["weight"]
        return apply_operation(api, "set_measurement", Measurement(**p.model_dump()))
    if operation == "sdk_set_new_goal":
        periods = api.request("GET", web + "/nutrient-goals")
        applicable = [
            g
            for g in periods
            if g.get("valid_from", "") <= p.calendar_date
            and (not g.get("valid_to") or g["valid_to"] >= p.calendar_date)
        ]
        if not applicable:
            raise ValueError("No goal period found")
        item = copy.deepcopy(max(applicable, key=lambda g: g["valid_from"]))
        unit = (
            p.energy_unit
            if p.energy_unit != "account"
            else api.client.user_metadata["unit_preferences"]["energy"]
        )
        energy, macros, mode = resolve_goal(p, item["default_goal"], unit)
        for field in ("valid_to", "default_group_id", "updated_at"):
            item.pop(field, None)
        item["valid_from"] = p.calendar_date
        for goal in [item["default_goal"], *item["daily_goals"]]:
            goal["energy"] = {"value": str(energy), "unit": unit}
            goal.update(macros)
            goal[
                "meal_goals"
            ] = []  # Match the SDK's documented request implementation.
            goal.pop("group_id", None)
        response = api.request("POST", web + "/nutrient-goals", {"item": item})
        return {
            "server_response": response,
            "submitted": {"energy": energy, "energy_unit": unit, **macros},
            "mode": mode,
            "effects": "Replaces all daily energy/macros and clears per-meal goals, as the SDK does. Server may round values.",
        }
    if (
        operation in ("add_food_to_diary", "update_food_diary_entry")
        and p.meal_name is not None
    ):
        profile = api.request("GET", web + "/diary/profile")
        meals = profile.get("diary_preferences", {}).get("meal_names", [])
        if p.meal_name not in meals:
            matches = [
                name for name in meals
                if isinstance(name, str)
                and name.strip().casefold() == p.meal_name.strip().casefold()
            ]
            if len(matches) != 1:
                raise ValueError(
                    "Unknown meal name; read account_preferences and use an exact meal name"
                )
            p.meal_name = matches[0]
    if operation == "add_food_to_diary":
        food = food_item(api, p.food_id)
        servings = [
            s
            for s in food.get("serving_sizes", [])
            if s.get("index") == p.serving_index
        ]
        if len(servings) != 1:
            raise ValueError(
                "Exact serving_index was not found; call get_food_details again"
            )
        serving = {k: servings[0][k] for k in ("value", "unit", "nutrition_multiplier")}
        item = {
            "type": "food_entry",
            "date": p.calendar_date,
            "meal_name": p.meal_name,
            "servings": p.servings,
            "food": {"id": str(food["id"]), "version": str(food["version"])},
            "serving_size": serving,
        }
        return api.request("POST", "/v2/diary", {"items": [item]}, v2=True)
    if operation in ("update_food_diary_entry", "delete_food_diary_entry"):
        path = web + "/diary/" + p.entry_id
        before = api.request("GET", path)
        item = before.get("item", before)
        if item.get("type") != "food_entry":
            raise ValueError("Target is not a food diary entry")
        if operation.startswith("delete"):
            return api.request("DELETE", path)
        fields = p.model_dump(exclude_none=True, exclude={"entry_id"})
        return api.request("PATCH", path, fields)
    if operation == "set_water":
        return api.request(
            "POST",
            web + "/diary/water",
            {"date": p.calendar_date, "units": "milliliters", "value": p.milliliters},
        )
    if operation == "set_measurement":
        types = api.request("GET", "/api/user-measurements/measurements/types")
        if p.measurement not in [t.get("description") for t in types]:
            raise ValueError("Unknown measurement type; read measurement_types first")
        return api.request(
            "PUT",
            "/api/user-measurements/measurements",
            {
                "items": [
                    {
                        "type": p.measurement,
                        "date": p.calendar_date,
                        "value": p.value,
                        "unit": p.unit,
                    }
                ]
            },
        )
    if operation == "delete_measurement":
        path = "/api/user-measurements/measurements/" + p.entry_id
        api.request("GET", path)
        return api.request("DELETE", path)
    if operation == "set_nutrition_goals":
        periods = api.request("GET", web + "/nutrient-goals")
        applicable = [
            g
            for g in periods
            if g.get("valid_from", "") <= p.calendar_date
            and (not g.get("valid_to") or g["valid_to"] >= p.calendar_date)
        ]
        if not applicable:
            raise ValueError("No current goal period found for the requested date")
        item = copy.deepcopy(max(applicable, key=lambda g: g["valid_from"]))
        for field in ("valid_to", "default_group_id", "updated_at"):
            item.pop(field, None)
        item["valid_from"] = p.calendar_date
        for goal in [item["default_goal"], *item["daily_goals"]]:
            goal["energy"] = {"value": str(p.calories), "unit": "calories"}
            for field in ("carbohydrates", "protein", "fat"):
                goal[field] = getattr(p, field)
        return api.request("POST", web + "/nutrient-goals", {"item": item})
    if operation == "create_custom_food":
        return api.request("POST", web + "/foods", {"item": custom_payload(p)})
    if operation in ("update_custom_food", "delete_custom_food"):
        owned = api.request("GET", web + "/users/foods/mine", params={"search": ""})
        if p.food_id not in [str(f["id"]) for f in owned]:
            raise ValueError("Food is not in the signed-in account's custom foods")
        path = web + "/foods/" + p.food_id
        if operation.startswith("delete"):
            return api.request("DELETE", path)
        return api.request("PATCH", path, {"item": custom_payload(p)})
    UUID(p.entry_id)
    path = "/v2/diary/fasting_entry"
    if operation == "delete_fast":
        return api.request("DELETE", path + "/" + p.entry_id, v2=True)
    payload = {
        "items": [
            {
                "type": "fasting_entry",
                "id": p.entry_id.upper(),
                "fast_started": p.fast_started,
                "fast_ended": p.fast_ended,
            }
        ]
    }
    return api.request(
        "POST" if operation == "log_fast" else "PATCH",
        path if operation == "log_fast" else path + "/" + p.entry_id,
        payload,
        v2=True,
    )


def write_schema(operation):
    return {
        "operation": operation,
        "parameters": MODELS[operation].model_json_schema(),
        "enabled_by_default": True,
        "live_write_verification": "not yet performed",
        "instructions": "Use a unique idempotency_key per intended change. Reuse it for retries. Never retry an unknown outcome with a new key.",
    }


class Writer:
    def __init__(self, service, directory=None):
        self.service = service
        self.store = TokenStore(directory or data_directory() / "write-ledger")

    def execute(self, operation, parameters, idempotency_key):
        if operation not in MODELS:
            raise ValueError("Unsupported write operation")
        if not re.fullmatch(r"[A-Za-z0-9_-]{8,100}", idempotency_key):
            raise ValueError(
                "Use an 8–100 character idempotency key containing letters, digits, _ or -"
            )
        try:
            p = MODELS[operation].model_validate(parameters)
        except ValidationError:
            raise ValueError(
                "Invalid write input. Call get_myfitnesspal_write_schema for the exact required fields."
            ) from None
        if isinstance(p, (SdkGoal, SdkMeasurement)) and p.calendar_date is None:
            p.calendar_date = self.service.today().isoformat()
        fingerprint = hashlib.sha256(
            json.dumps([operation, p.model_dump()], sort_keys=True).encode()
        ).hexdigest()
        client = self.service.call(lambda c: c)
        owner = hashlib.sha256(client.effective_username.encode()).hexdigest()
        key = hashlib.sha256((owner + idempotency_key).encode()).hexdigest()
        with session_lock(self.store):
            ledger = json.loads(self.store.load()) if self.store.exists() else {}
            previous = ledger.get(key)
            if previous:
                if previous["fingerprint"] != fingerprint:
                    raise ValueError(
                        "Idempotency key already belongs to another change"
                    )
                if previous["result"]["status"] != "failed_before_write":
                    return previous["result"]
            if len(ledger) >= 10000:
                raise ValueError(
                    "Write ledger is full; archive it locally before further writes"
                )
            result = {
                "operation": operation,
                "status": "outcome_unknown",
                "message": "A previous attempt may have changed the account. Inspect MyFitnessPal before retrying.",
                "verification": "not_verified",
            }
            ledger[key] = {"fingerprint": fingerprint, "result": result}
            self.store.save(json.dumps(ledger))
            api = Api(client)
            try:
                data = apply_operation(api, operation, p)
                result = {
                    "operation": operation,
                    "status": "acknowledged",
                    "data": data,
                    "verification": "server_acknowledged; read back before claiming persisted values",
                }
            except Exception as error:
                if not api.write_sent:
                    reasons = {
                        "Unknown meal name; read account_preferences and use an exact meal name": "unknown_meal_name",
                        "Exact serving_index was not found; call get_food_details again": "serving_index_not_found",
                        "Food lookup did not return the exact requested ID": "food_id_mismatch",
                    }
                    reason = reasons.get(str(error), "preflight_failed")
                    if isinstance(error, UpstreamFailure) and error.status_code:
                        reason = "upstream_http_error"
                    result = {
                        "operation": operation,
                        "status": "failed_before_write",
                        "message": "Validation, authentication or target lookup failed. No mutation request was sent.",
                        "stage": api.stage,
                        "reason": reason,
                        "http_status": error.status_code if isinstance(error, UpstreamFailure) else None,
                        "retry_safe": True,
                    }
                self.service._client = None
            ledger[key]["result"] = result
            self.store.save(json.dumps(ledger))
            return result
