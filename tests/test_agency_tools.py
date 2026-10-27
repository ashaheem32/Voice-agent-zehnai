import json

import pytest
from google.genai import types

from app.bridge import BrowserBridge
from app.config import settings, system_prompt
from app.store import Store
from app.tools import agency
from app.tools.registry import ToolError, ToolRegistry


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(agency, "store", Store(tmp_path / "agency_requests.json"))


def request(**overrides):
    details = dict(name="Sara", contact="sara@example.com", service="google ads",
                   project_details="Generate enquiries for a design studio", confirmed=True)
    return agency.request_consultation(**{**details, **overrides})


def test_active_agent_exposes_agency_tools_without_hotel_booking():
    registry = ToolRegistry(settings.tool_modules)
    assert set(registry.tools) == {"get_agency_info", "get_service_info", "request_consultation", "end_call"}
    prompt = system_prompt(settings.persona_file)
    assert "ZehnAI" in prompt and "Saffron" not in prompt
    assert len(registry.declarations) == 4


@pytest.mark.parametrize("service,key", [
    ("Google Ads", "google_ads"), ("SEO", "seo"), ("voice agent", "ai_calling_agents"),
    ("automation", "workflow_automation"), ("website", "web_development"),
    ("mobile app", "app_development"), ("UI/UX", "ui_ux_design"),
])
def test_service_lookup_matches_spoken_names(service, key):
    result = agency.get_service_info(service)
    assert result["service"] == key
    assert result["source_url"].startswith("https://www.zehnai.tech/")


def test_unknown_service_is_not_invented():
    with pytest.raises(ToolError, match="not in the verified catalogue"):
        agency.get_service_info("hotel rooms")
    assert agency.store.all("enquiries") == []


@pytest.mark.parametrize("overrides,error", [
    ({"confirmed": False}, "permission"), ({"confirmed": "true"}, "permission"),
    ({"name": " "}, "name"), ({"project_details": ""}, "description"),
    ({"contact": "invalid"}, "email address or phone"),
    ({"contact": "abc1234567"}, "email address or phone"),
    ({"contact": "123"}, "email address or phone"),
    ({"service": "hotel rooms"}, "not in the verified catalogue"),
])
def test_invalid_or_unconfirmed_request_is_not_saved(overrides, error):
    with pytest.raises(ToolError, match=error):
        request(**overrides)
    assert agency.store.all("enquiries") == []
    assert not agency.store.path.exists()


@pytest.mark.parametrize("contact", ["sara@example.com", "+971 50 123 4567"])
def test_confirmed_request_is_persisted_as_local_only(contact):
    result = request(contact=contact, company="Design studio", preferred_time="Tomorrow afternoon")
    assert result["status"] == "saved_locally"
    assert result["service"] == "google_ads"
    assert "not been notified" in result["message"]
    saved = Store(agency.store.path).all("enquiries")
    assert len(saved) == 1
    assert saved[0]["contact"] == contact
    assert saved[0]["preferred_time"] == "Tomorrow afternoon"
    assert request()["code"] != result["code"]


def test_general_human_enquiry_can_be_saved_without_claiming_a_service():
    assert request(service="general")["service_name"] == "General enquiry"


async def test_registry_returns_validation_errors_without_saving():
    registry = ToolRegistry(("app.tools.agency", "app.tools.call"))
    result = await registry.call(types.FunctionCall(id="c1", name="request_consultation", args={
        "name": "Sara", "contact": "sara@example.com", "service": "seo",
        "project_details": "Improve search presence", "confirmed": False,
    }))
    assert "permission" in result.response["error"]
    assert agency.store.all("enquiries") == []


async def test_consultation_event_refreshes_agency_panel(monkeypatch):
    import app.bridge as bridge_module

    class Socket:
        def __init__(self):
            self.events = []

        async def send_text(self, text):
            self.events.append(json.loads(text))

    monkeypatch.setattr(bridge_module, "store", agency.store)
    request()
    socket = Socket()
    bridge = BrowserBridge(socket)
    await bridge.tool_event({"phase": "end", "name": "request_consultation", "result": {"status": "saved_locally"}})
    assert [e["type"] for e in socket.events] == ["tool", "enquiries"]
    assert socket.events[1]["enquiries"][0]["name"] == "Sara"
    await bridge.tool_event({"phase": "end", "name": "end_call", "result": {"status": "Call ended."}})
    assert socket.events[-1] == {"type": "hangup"}
