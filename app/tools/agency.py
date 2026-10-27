"""Verified ZehnAI service information and locally saved consultation requests."""

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from uuid import uuid4

from app.store import store
from app.tools.registry import ToolError, tool

AGENCY = json.loads((Path(__file__).parent.parent / "data" / "agency.json").read_text(encoding="utf-8"))
SERVICES = AGENCY["services"]


def find_service(service: str) -> str:
    wanted = service.strip().lower()
    if wanted == "general":
        return "general"
    for key, entry in SERVICES.items():
        if wanted in (key, entry["name"].lower(), *entry["aliases"]):
            return key
    raise ToolError("That service is not in the verified catalogue. Use general for a request that needs agency confirmation.")


@tool
def get_agency_info(topic: Literal["overview", "services", "pricing", "process", "contact"]) -> dict:
    """Look up verified ZehnAI services, pricing policy, process, or contact information.

    Args:
        topic: The subject the caller asked about.
    """
    provenance = {key: AGENCY[key] for key in ("source_url", "verified_on", "coverage")}
    if topic in ("overview", "services"):
        return {"name": AGENCY["name"], "website": AGENCY["website"], "categories": AGENCY["categories"], "services": SERVICES, **provenance}
    if topic not in AGENCY["info"]:
        raise ToolError("I can help with overview, services, pricing, process, or contact.")
    return {"info": AGENCY["info"][topic], **provenance}


@tool
def get_service_info(service: str) -> dict:
    """Look up a service's verified scope. Never infer unlisted capabilities.

    Args:
        service: Service name or ID, such as seo, google_ads, meta_ads, or social_media.
    """
    key = find_service(service)
    if key == "general":
        raise ToolError("Please ask which service the caller needs, or use get_agency_info for the catalogue.")
    return {"service": key, **SERVICES[key], "source_url": AGENCY["source_url"], "pricing": AGENCY["info"]["pricing"]}


@tool
def request_consultation(name: str, contact: str, service: str, project_details: str,
                         confirmed: bool, company: str = "", preferred_time: str = "") -> dict:
    """Save a consultation or human callback request locally after the caller confirms the read-back.

    This does not contact ZehnAI, send messages, check calendars, or book an appointment.

    Args:
        name: Caller's name.
        contact: Email address or phone number supplied by the caller.
        service: Verified service name or ID; general for an unverified service or other human enquiry.
        project_details: Caller's goal, questions, and any volunteered budget or timing requirements.
        confirmed: True only after reading back the details and receiving explicit agreement to save them.
        company: Optional company or business name.
        preferred_time: Optional callback preference; not a confirmed appointment.
    """
    if confirmed is not True:
        raise ToolError("Read back the request and contact details, and ask for permission to save them first.")
    if not name.strip() or not project_details.strip():
        raise ToolError("Please provide the caller's name and a short description of what they need.")
    contact = contact.strip()
    email = re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", contact)
    phone = re.fullmatch(r"\+?[\d\s().-]+", contact)
    if not email and not (phone and 7 <= len(re.sub(r"\D", "", contact)) <= 15):
        raise ToolError("Please repeat a valid email address or phone number for the request.")
    key = find_service(service)
    request = store.add("enquiries", {
        "code": f"ZAI-{uuid4().hex[:8].upper()}",
        "name": name.strip(), "contact": contact,
        "service": key, "service_name": SERVICES[key]["name"] if key != "general" else "General enquiry",
        "project_details": project_details.strip(), "company": company.strip(),
        "preferred_time": preferred_time.strip(), "status": "saved_locally",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    return {**request, "message": "Request saved locally only. ZehnAI has not been notified and no appointment is booked. For follow-up, submit the request through the agency website contact form."}
