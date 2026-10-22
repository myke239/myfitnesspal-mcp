import copy
import json
from types import SimpleNamespace

import pytest

from myfitnesspal_mcp.operations import MODELS, Writer, apply_operation
from myfitnesspal_mcp.service import Service

DATE = "2026-10-15"
FAST_ID = "550e8400-e29b-41d4-a716-446655440000"
FOOD = {
    "description": "Test food",
    "serving_amount": 100,
    "serving_unit": "g",
    "nutrients": {"calories": 100, "carbohydrates": 20, "protein": 2, "fat": 1},
}


class FakeApi:
    def __init__(self):
        self.calls = []

    def request(self, method, path, payload=None, params=None, v2=False):
        self.calls.append((method, path, copy.deepcopy(payload)))
        if method != "GET":
            return {"items": [{"id": FAST_ID}]}
        if path.endswith("/diary/profile"):
            return {
                "diary_preferences": {
                    "meal_names": ["Breakfast", "Lunch", "Dinner", "Snacks"]
                }
            }
        if path == "/v2/foods/123":
            return {
                "item": {
                    "id": "123",
                    "version": "v2",
                    "serving_sizes": [
                        {
                            "index": 0,
                            "value": 100,
                            "unit": "g",
                            "nutrition_multiplier": 1,
                        }
                    ],
                }
            }
        if path.endswith("/foods/mine"):
            return [{"id": "123"}]
        if path.endswith("measurements/types"):
            return [{"description": "Weight"}]
        if path.endswith("nutrient-goals"):
            return [
                {
                    "valid_from": "2026-01-01",
                    "default_goal": {"fiber": 25, "meal_goals": [1]},
                    "daily_goals": [
                        {"day_of_week": day, "sodium": 2300}
                        for day in (
                            "monday",
                            "tuesday",
                            "wednesday",
                            "thursday",
                            "friday",
                            "saturday",
                            "sunday",
                        )
                    ],
                }
            ]
        return {"item": {"type": "food_entry"}}


@pytest.mark.parametrize(
    "operation,parameters,method,path",
    [
        (
            "add_food_to_diary",
            {
                "calendar_date": DATE,
                "food_id": "123",
                "meal_name": "Breakfast",
                "servings": 1,
                "serving_index": 0,
            },
            "POST",
            "/v2/diary",
        ),
        (
            "update_food_diary_entry",
            {"entry_id": FAST_ID, "servings": 2},
            "PATCH",
            "/api/services/diary/" + FAST_ID,
        ),
        (
            "delete_food_diary_entry",
            {"entry_id": FAST_ID},
            "DELETE",
            "/api/services/diary/" + FAST_ID,
        ),
        (
            "set_water",
            {"calendar_date": DATE, "milliliters": 500},
            "POST",
            "/api/services/diary/water",
        ),
        (
            "set_measurement",
            {"calendar_date": DATE, "measurement": "Weight", "value": 70, "unit": "kg"},
            "PUT",
            "/api/user-measurements/measurements",
        ),
        (
            "delete_measurement",
            {"entry_id": "123"},
            "DELETE",
            "/api/user-measurements/measurements/123",
        ),
        (
            "set_nutrition_goals",
            {
                "calendar_date": DATE,
                "calories": 2100,
                "carbohydrates": 250,
                "protein": 150,
                "fat": 50,
            },
            "POST",
            "/api/services/nutrient-goals",
        ),
        ("create_custom_food", FOOD, "POST", "/api/services/foods"),
        (
            "update_custom_food",
            {**FOOD, "food_id": "123"},
            "PATCH",
            "/api/services/foods/123",
        ),
        ("delete_custom_food", {"food_id": "123"}, "DELETE", "/api/services/foods/123"),
        (
            "log_fast",
            {
                "entry_id": FAST_ID,
                "fast_started": "2026-10-14T20:00:00-07:00",
                "fast_ended": "2026-10-15T08:00:00-07:00",
            },
            "POST",
            "/v2/diary/fasting_entry",
        ),
        (
            "update_fast",
            {
                "entry_id": FAST_ID,
                "fast_started": "2026-10-14T20:00:00Z",
                "fast_ended": "2026-10-15T08:00:00Z",
            },
            "PATCH",
            "/v2/diary/fasting_entry/" + FAST_ID,
        ),
        (
            "delete_fast",
            {"entry_id": FAST_ID},
            "DELETE",
            "/v2/diary/fasting_entry/" + FAST_ID,
        ),
    ],
)
def test_operation_routes_and_payloads(operation, parameters, method, path):
    api = FakeApi()
    apply_operation(api, operation, MODELS[operation].model_validate(parameters))
    assert api.calls[-1][:2] == (method, path)
    payload = api.calls[-1][2]
    if operation == "set_nutrition_goals":
        assert payload["item"]["default_goal"]["fiber"] == 25
        assert len(payload["item"]["daily_goals"]) == 7
        assert all(g["sodium"] == 2300 for g in payload["item"]["daily_goals"])
        assert payload["item"]["default_goal"]["meal_goals"] == [1]
    if operation == "add_food_to_diary":
        assert payload["items"][0]["food"]["version"] == "v2"
    if operation == "log_fast":
        assert payload["items"][0]["fast_started"] == "2026-10-15T03:00:00Z"


def test_exact_serving_and_owned_food_required():
    api = FakeApi()
    with pytest.raises(ValueError):
        apply_operation(
            api,
            "add_food_to_diary",
            MODELS["add_food_to_diary"](
                calendar_date=DATE,
                food_id="123",
                meal_name="Breakfast",
                servings=1,
                serving_index=9,
            ),
        )
    assert all(c[0] == "GET" for c in api.calls)
    with pytest.raises(ValueError):
        apply_operation(
            api, "delete_custom_food", MODELS["delete_custom_food"](food_id="999")
        )
    assert all(c[0] == "GET" for c in api.calls)


@pytest.mark.parametrize(
    "parameters",
    [
        {"calendar_date": "today", "milliliters": 500},
        {"calendar_date": DATE, "milliliters": float("nan")},
        {"calendar_date": DATE, "milliliters": -1},
        {"calendar_date": DATE, "milliliters": 500, "url": "https://evil.example"},
    ],
)
def test_invalid_write_never_authenticates(tmp_path, parameters):
    def forbidden():
        pytest.fail("Invalid input accessed authentication")

    with pytest.raises(ValueError):
        Writer(Service(forbidden), tmp_path / "writes").execute(
            "set_water", parameters, "request_001"
        )


class Session:
    def __init__(self, fail=False):
        self.posts = 0
        self.fail = fail

    def get(self, *args, **kwargs):
        return SimpleNamespace(
            status_code=200, json=lambda: {"csrfToken": "private-csrf"}
        )

    def request(self, method, url, **kwargs):
        assert kwargs["allow_redirects"] is False
        assert kwargs["timeout"] == (10, 30)
        self.posts += 1
        if self.fail:
            raise TimeoutError("private upstream secret")
        return SimpleNamespace(
            status_code=200,
            content=b"{}",
            json=lambda: {"date": DATE, "milliliters": 500},
        )


@pytest.mark.parametrize("fail", [False, True])
def test_durable_idempotency_and_unknown_outcome(tmp_path, fail):
    session = Session(fail)
    client = SimpleNamespace(effective_username="owner", session=session)
    service = Service(lambda: client)
    path = tmp_path / "writes"
    parameters = {"calendar_date": DATE, "milliliters": 500}
    result = Writer(service, path).execute("set_water", parameters, "request_001")
    assert result["status"] == ("outcome_unknown" if fail else "acknowledged")
    assert "private" not in json.dumps(result)
    assert (
        Writer(service, path).execute("set_water", parameters, "request_001") == result
    )
    assert session.posts == 1

    with pytest.raises(ValueError):
        Writer(service, path).execute(
            "set_water", {**parameters, "milliliters": 1000}, "request_001"
        )
    assert session.posts == 1


def test_preflight_failure_is_diagnostic_and_safe_to_retry(tmp_path, monkeypatch):
    from myfitnesspal_mcp import operations

    attempts = []

    def apply(api, operation, parameters):
        attempts.append(operation)
        api.stage = "food_lookup"
        if len(attempts) == 1:
            raise operations.UpstreamFailure("secret response", 401)
        api.write_sent = True
        return {"id": "saved"}

    monkeypatch.setattr(operations, "apply_operation", apply)
    writer = Writer(Service(lambda: SimpleNamespace(effective_username="owner")), tmp_path)
    parameters = {"calendar_date": DATE, "milliliters": 500}
    result = writer.execute("set_water", parameters, "retry_request")
    assert result["status"] == "failed_before_write"
    assert result["stage"] == "food_lookup"
    assert result["http_status"] == 401
    assert result["retry_safe"] is True
    assert "secret" not in json.dumps(result)
    assert writer.execute("set_water", parameters, "retry_request")["status"] == "acknowledged"
    writer.execute("set_water", parameters, "retry_request")
    assert len(attempts) == 2

@pytest.mark.parametrize('operation', ['add_food_to_diary', 'update_food_diary_entry'])
@pytest.mark.parametrize('meal_name', ['lunch', 'LUNCH', ' Lunch '])
def test_diary_meal_name_resolves_account_capitalization(operation, meal_name):
    api = FakeApi()
    parameters = ({'calendar_date': DATE, 'food_id': '123', 'servings': 1,
                   'serving_index': 0} if operation == 'add_food_to_diary'
                  else {'entry_id': FAST_ID})
    parameters['meal_name'] = meal_name
    apply_operation(api, operation, MODELS[operation].model_validate(parameters))
    method, path, body = api.calls[-1]
    assert method in ('POST', 'PATCH')
    assert (body['items'][0] if operation == 'add_food_to_diary' else body)['meal_name'] == 'Lunch'


@pytest.mark.parametrize('meals,requested', [(['Lunch'], 'Brunch'), (['Lunch', 'LUNCH'], 'lunch')])
def test_unrecognized_or_ambiguous_meal_never_submits(meals, requested):
    class MealsApi(FakeApi):
        def request(self, method, path, *args, **kwargs):
            if path.endswith('/diary/profile'):
                self.calls.append((method, path, None))
                return {'diary_preferences': {'meal_names': meals}}
            return super().request(method, path, *args, **kwargs)
    api = MealsApi()
    p = MODELS['add_food_to_diary'].model_validate({
        'calendar_date': DATE, 'food_id': '123', 'meal_name': requested,
        'servings': 1, 'serving_index': 0})
    with pytest.raises(ValueError, match='Unknown meal name'):
        apply_operation(api, 'add_food_to_diary', p)
    assert all(method == 'GET' for method, _, _ in api.calls)
