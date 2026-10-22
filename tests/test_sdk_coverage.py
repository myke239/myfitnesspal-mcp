import ast
import copy
import inspect
import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import myfitnesspal
import pytest
from pydantic import ValidationError

from myfitnesspal_mcp.coverage import sdk_coverage
from myfitnesspal_mcp.operations import (
    CustomFood,
    SdkFood,
    SdkGoal,
    SdkMeasurement,
    apply_operation,
    custom_payload,
    resolve_goal,
)
from myfitnesspal_mcp.service import Service


def test_inventory_covers_every_public_sdk_operation():
    source = Path(inspect.getfile(myfitnesspal.Client)).read_text(encoding="utf-8")
    client = next(
        n
        for n in ast.parse(source).body
        if isinstance(n, ast.ClassDef) and n.name == "Client"
    )
    methods = {
        n.name
        for n in client.body
        if isinstance(n, ast.FunctionDef)
        and not n.name.startswith("_")
        and not any(
            isinstance(d, ast.Name) and d.id == "property" for d in n.decorator_list
        )
    }
    assert methods == {m["sdk_method"] for m in sdk_coverage()["operations"]}
    assert len(methods) == 12
    assert set(inspect.signature(myfitnesspal.Client.set_new_food).parameters) - {
        "self"
    } == set(SdkFood.model_fields)
    assert set(inspect.signature(myfitnesspal.Client.set_new_goal).parameters) - {
        "self"
    } == set(SdkGoal.model_fields) - {"calendar_date"}


@pytest.mark.parametrize(
    "unit,mode",
    [
        (u, m)
        for u in ("calories", "kilojoules")
        for m in ("absolute", "percent", "energy")
    ],
)
def test_goal_calculation_matches_real_sdk(unit, mode):
    previous = {
        "energy": {"value": 2000, "unit": "calories"},
        "carbohydrates": 250,
        "protein": 100,
        "fat": 66,
    }
    values = {"energy": 1000 if unit == "calories" else 4184, "energy_unit": unit}
    if mode == "absolute":
        values.update(carbohydrates=250, protein=100, fat=70)
    if mode == "percent":
        values.update(percent_carbohydrates=50, percent_protein=25, percent_fat=25)
    submitted = []

    class Session:
        headers = {}

        def get(self, *args, **kwargs):
            return SimpleNamespace(
                text=json.dumps(
                    {
                        "items": [
                            {"default_goal": copy.deepcopy(previous), "daily_goals": []}
                        ]
                    }
                )
            )

        def post(self, url, body, **kwargs):
            submitted.append(json.loads(body))
            return SimpleNamespace(ok=True)

    client = myfitnesspal.Client.__new__(myfitnesspal.Client)
    client.session = Session()
    client._auth_data = {"access_token": "test-token", "user_id": "1"}
    client._user_metadata = {"unit_preferences": {"energy": "calories"}}
    client.set_new_goal(**values)
    energy, macros, _ = resolve_goal(SdkGoal(**values), previous, unit)
    expected = submitted[0]["item"]["default_goal"]
    assert energy == pytest.approx(expected["energy"]["value"])
    for k, v in macros.items():
        assert v == pytest.approx(expected[k])


@pytest.mark.parametrize(
    "extra",
    [
        {"carbohydrates": 100},
        {"percent_carbohydrates": 40, "percent_protein": 20, "percent_fat": 20},
        {"carbohydrates": 100, "protein": 100, "fat": 50, "percent_fat": 25},
    ],
)
def test_ambiguous_goals_are_rejected(extra):
    with pytest.raises(ValidationError):
        SdkGoal(energy=2000, **extra)


def test_all_food_nutrients_and_container_mapping():
    p = CustomFood(
        description="Food",
        serving_amount=100,
        serving_unit="g",
        servings_per_container=3,
        nutrients={
            "calories": 100,
            "carbohydrates": 10,
            "protein": 5,
            "fat": 3,
            "vitamin_a": 20,
            "vitamin_c": 30,
            "calcium": 40,
            "iron": 50,
        },
    )
    item = custom_payload(p)
    assert item["nutritional_contents"]["iron"] == 50
    assert item["serving_sizes"][1]["nutrition_multiplier"] == 3
    assert item["public"] is False


class ReadClient:
    effective_username = "owner"

    def get_report(self, **kwargs):
        self.bounds = kwargs
        return {date(2026, 10, 1): 12}

    def get_recipes(self):
        return {str(i): f"Recipe {i}" for i in range(3)}

    def get_recipe(self, recipe_id):
        return {
            "name": "Recipe",
            "recipeIngredient": ["Flour"],
            "recipeYield": "2",
            "tags": ["MFP"],
        }

    def get_meals(self):
        return {"42": "Actual title"}

    def get_meal(self, meal_id, meal_title):
        assert (meal_id, meal_title) == (42, "Actual title")
        return {"name": meal_title, "recipeIngredient": ["Food"]}

    def get_measurements(self, measurement, lower_bound, upper_bound):
        self.bounds = (measurement, lower_bound, upper_bound)
        return {lower_bound: 100}

    def get_date(self, selected, **kwargs):
        self.diary_args = kwargs
        entry = SimpleNamespace(
            name="Rice, 2 cups",
            short_name="Rice",
            quantity="2",
            unit="cups",
            nutrition_information={"calories": 400},
        )
        return SimpleNamespace(
            complete=True,
            totals={"calories": 400},
            goals={"calories": 2000},
            notes="Owner note",
            meals=[
                SimpleNamespace(name="Lunch", totals={"calories": 400}, entries=[entry])
            ],
        )


def test_reads_defaults_paging_and_diary_privacy():
    client = ReadClient()
    service = Service(lambda: client, today=lambda: date(2026, 10, 15))
    assert service.recipes(0, 2)["next_cursor"] == 2
    assert len(service.recipes(2, 2)["items"]) == 1
    assert service.saved_meal("42")["name"] == "Actual title"
    assert service.recipe("1")["recipeIngredient"] == ["Flour"]
    report = service.report(start_date="2026-10-15", end_date="2026-01-01")
    assert report["start_date"] == "2026-01-01" and report["warnings"]
    service.measurements()
    assert client.bounds == ("Weight", date(2026, 9, 15), date(2026, 10, 15))
    own = service.diary("2026-10-15")
    assert own["notes"]["body"] == "Owner note"
    assert own["meals"][0]["entries"][0]["quantity"] == "2"
    friend = service.diary("2026-10-15", friend_username="friend")
    assert friend["notes"] is None
    assert client.diary_args == {"friend_username": "friend"}
    assert service.diary("2026-10-15", username="friend")["notes"] is None


def test_report_rejects_url_injection_without_auth():
    def forbidden():
        pytest.fail("Invalid input accessed authentication")

    with pytest.raises(ValueError):
        Service(forbidden).report(report_name="../../user/auth_token?x=1")


def test_sdk_food_write_adapter_keeps_all_options():
    calls = []
    api = SimpleNamespace(request=lambda *args, **kwargs: calls.append(args))
    spec = SdkFood(
        brand="Brand",
        description="Food",
        calories=200,
        fat=2,
        carbs=20,
        protein=10,
        serving_size="2 tbsp",
        servingspercontainer=5,
        sharepublic=True,
        vitamin_a=50,
        calcium=30,
        vitamin_c=20,
        iron=15,
        trans_fat=0,
    )
    apply_operation(api, "sdk_set_new_food", spec)
    item = calls[0][2]["item"]
    assert item["public"] is True
    assert item["brand_name"] == "Brand"
    assert item["serving_sizes"][0]["unit"] == "2 tbsp"
    assert item["serving_sizes"][1]["nutrition_multiplier"] == 5
    assert item["nutritional_contents"]["vitamin_a"] == 50
    assert item["nutritional_contents"]["trans_fat"] == 0


def test_sdk_measurement_uses_account_weight_unit():
    writes = []

    class Api:
        client = SimpleNamespace(user_metadata={"unit_preferences": {"weight": "kg"}})

        def request(self, method, path, payload=None, **kwargs):
            if method == "GET":
                return [{"description": "Weight"}, {"description": "Waist"}]
            writes.append(payload)

    apply_operation(
        Api(),
        "sdk_set_measurements",
        SdkMeasurement(value=70, calendar_date="2026-10-15"),
    )
    assert writes[0]["items"][0]["unit"] == "kg"
    with pytest.raises(ValueError):
        apply_operation(
            Api(),
            "sdk_set_measurements",
            SdkMeasurement(measurement="Waist", value=80, calendar_date="2026-10-15"),
        )
    assert len(writes) == 1


def test_timezone_default_is_available_on_windows():
    from myfitnesspal_mcp.service import local_today

    assert isinstance(local_today(), date)
