"""Map parsed HL7 v2 segments to FHIR R4 resources.

v2 -> R4 field tables follow the HL7 v2-to-FHIR mapping catalog for the
segments this bridge covers (MSH, PID, PV1, OBR, OBX). Where the catalog
allows options, the choice is noted in the README.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from .parser import Segment, segments_of

NAMESPACE = uuid.UUID("6ba7b811-9dad-11d1-80b4-00c04fd430c8")  # urn:uuid NAMESPACE_URL

# v2 table 0085 (result status) -> R4 Observation.status / DiagnosticReport.status
RESULT_STATUS = {
    "F": "final",
    "P": "preliminary",
    "C": "corrected",
    "D": "entered-in-error",
}

# v2 table 0004 (patient class) -> v3 ActCode encounter class
ENCOUNTER_CLASS = {
    "I": ("IMP", "inpatient encounter"),
    "E": ("EMER", "emergency"),
    "O": ("AMB", "ambulatory"),
    "P": ("PRENC", "preadmit"),
}

GENDER = {"M": "male", "F": "female", "O": "other", "U": "unknown"}

# Coding system table 0396 (subset) -> canonical URL
CODE_SYSTEMS = {
    "LN": "http://loinc.org",
    "UCUM": "http://unitsofmeasure.org",
    "NHI": "https://www.nhi.gov.tw",
    "SNM": "http://snomed.info/sct",
}


def stable_uuid(kind: str, seed: str) -> str:
    return f"urn:uuid:{uuid.uuid5(NAMESPACE, f'hl7v2-fhir-bridge/{kind}/{seed}')}"


def _coding(field_obj, *, fallback_system: str | None = None) -> dict | None:
    """CE/CWE field (code^text^system) -> FHIR Coding."""
    code = field_obj.component(1)
    if not code:
        return None
    text = field_obj.component(2)
    system_raw = field_obj.component(3)
    system = CODE_SYSTEMS.get(system_raw.upper(), fallback_system if system_raw == "" else system_raw)
    coding: dict = {"code": code}
    if system:
        coding["system"] = system
    if text:
        coding["display"] = text
    return coding


def _ts(value: str) -> str | None:
    """v2 TS (YYYY[MM[DD[HH[MM[SS]]]]]) -> FHIR dateTime/date string."""
    digits = value.split(".")[0].split("+")[0]
    if len(digits) < 4 or not digits.isdigit():
        return None
    year = digits[0:4]
    month = digits[4:6] or "01"
    day = digits[6:8] or "01"
    if len(digits) <= 8:
        return f"{year}-{month}-{day}"
    hour = digits[8:10] or "00"
    minute = digits[10:12] or "00"
    second = digits[12:14] or "00"
    return f"{year}-{month}-{day}T{hour}:{minute}:{second}"


def map_message_header(msh: Segment) -> tuple[dict, str]:
    control_id = msh.field(10)
    full_url = stable_uuid("MessageHeader", control_id)
    resource = {
        "resourceType": "MessageHeader",
        "id": uuid.uuid5(NAMESPACE, f"MessageHeader/{control_id}").hex[:24],
        "eventCoding": {
            "system": "http://terminology.hl7.org/CodeSystem/v2-0003",
            "code": msh.component(9, 2) or "R01",
        },
        "source": {"name": msh.component(3, 1) or "unknown-source"},
    }
    destination_app = msh.component(5, 1)
    if destination_app:
        resource["destination"] = [{"name": destination_app}]
    return resource, full_url


def map_patient(pid: Segment) -> tuple[dict, str]:
    identifiers = []
    for rep in pid.field_obj(3).repetitions:
        if not rep or not rep[0]:
            continue
        identifier: dict = {"value": rep[0]}
        authority = rep[3] if len(rep) > 3 and rep[3] else None
        if authority:
            identifier["system"] = CODE_SYSTEMS.get(authority.upper(), authority)
        identifiers.append(identifier)
    if not identifiers:
        # PID-3 is the identity anchor; synthesize a placeholder to keep references resolvable.
        identifiers.append({"value": f"unknown-{pid.component(2, 1) or uuid.uuid4().hex[:8]}"})

    name_family = pid.component(5, 1)
    name_given = pid.component(5, 2)
    human_name: dict = {}
    if name_family:
        human_name["family"] = name_family
    if name_given:
        human_name["given"] = [name_given]

    patient: dict = {
        "resourceType": "Patient",
        "id": uuid.uuid5(NAMESPACE, f"Patient/{identifiers[0]['value']}").hex[:24],
        "identifier": identifiers,
    }
    if human_name:
        patient["name"] = [human_name]
    gender_raw = pid.field(8)
    if gender_raw:
        patient["gender"] = GENDER.get(gender_raw.upper(), "unknown")
    birth_date = _ts(pid.field(7))
    if birth_date:
        patient["birthDate"] = birth_date
    full_url = stable_uuid("Patient", identifiers[0]["value"])
    return patient, full_url


def map_encounter(pv1: Segment, patient_url: str) -> tuple[dict, str] | None:
    class_code = pv1.field(2)
    if not class_code:
        return None
    code, display = ENCOUNTER_CLASS.get(class_code.upper(), ("AMB", class_code))
    seed = f"{class_code}-{pv1.component(3, 1)}-{pv1.component(3, 2)}-{pv1.component(3, 3)}"
    full_url = stable_uuid("Encounter", seed)
    encounter: dict = {
        "resourceType": "Encounter",
        "id": uuid.uuid5(NAMESPACE, f"Encounter/{seed}").hex[:24],
        "status": "completed" if pv1.field(45) else "unknown",
        "class": {
            "system": "http://terminology.hl7.org/CodeSystem/v3-ActCode",
            "code": code,
            "display": display,
        },
        "subject": {"reference": patient_url},
    }
    location_parts = [pv1.component(3, i) for i in (1, 2, 3)]
    location = " ".join(p for p in location_parts if p)
    if location:
        encounter["location"] = [{"location": {"display": location}}]
    return encounter, full_url


def map_observation(obx: Segment, patient_url: str) -> tuple[dict | None, str | None]:
    coding = _coding(obx.field_obj(3))
    if coding is None:
        return None, None
    obs_id = obx.field(1) or uuid.uuid4().hex[:8]
    full_url = stable_uuid("Observation", obs_id)

    status = RESULT_STATUS.get(obx.field(11).upper(), "unknown")
    observation: dict = {
        "resourceType": "Observation",
        "id": uuid.uuid5(NAMESPACE, f"Observation/{obs_id}").hex[:24],
        "status": status,
        "code": {"coding": [coding]},
        "subject": {"reference": patient_url},
    }

    value_type = obx.field(2).upper()
    value_raw = obx.field(5)
    unit = obx.field(6)
    if value_raw:
        if value_type == "NM":
            try:
                quantity: dict = {"value": float(value_raw)}
                if unit:
                    quantity["unit"] = unit
                    quantity["system"] = "http://unitsofmeasure.org"
                    quantity["code"] = unit
                observation["valueQuantity"] = quantity
            except ValueError:
                observation["valueString"] = value_raw
        else:
            observation["valueString"] = value_raw

    effective = _ts(obx.field(14) or obx.field(19))
    if effective:
        observation["effectiveDateTime"] = effective

    reference_range = obx.field(7)
    if reference_range:
        observation["referenceRange"] = [{"text": reference_range}]

    return observation, full_url


def map_diagnostic_report(obr: Segment, patient_url: str, observation_urls: list[str]) -> tuple[dict, str]:
    coding = _coding(obr.field_obj(4)) or {"code": "UNKNOWN"}
    order_number = obr.field(3) or obr.field(2)
    seed = order_number or uuid.uuid4().hex[:8]
    full_url = stable_uuid("DiagnosticReport", seed)
    report: dict = {
        "resourceType": "DiagnosticReport",
        "id": uuid.uuid5(NAMESPACE, f"DiagnosticReport/{seed}").hex[:24],
        "status": RESULT_STATUS.get(obr.field(25).upper(), "unknown"),
        "code": {"coding": [coding]},
        "subject": {"reference": patient_url},
    }
    effective = _ts(obr.field(7))
    if effective:
        report["effectiveDateTime"] = effective
    if observation_urls:
        report["result"] = [{"reference": u} for u in observation_urls]
    return report, full_url


def convert(segments: list[Segment], *, transaction: bool = False) -> dict:
    """Full message -> FHIR R4 Bundle."""
    msh_segments = segments_of(segments, "MSH")
    pid_segments = segments_of(segments, "PID")
    if not msh_segments or not pid_segments:
        raise ValueError("message needs at least MSH and PID segments")

    header, header_url = map_message_header(msh_segments[0])
    patient, patient_url = map_patient(pid_segments[0])

    entries: list[dict] = [
        {"fullUrl": header_url, "resource": header},
        {"fullUrl": patient_url, "resource": patient},
    ]

    pv1s = segments_of(segments, "PV1")
    if pv1s:
        mapped = map_encounter(pv1s[0], patient_url)
        if mapped:
            entries.append({"fullUrl": mapped[1], "resource": mapped[0]})

    # Walk in order: each OBR owns the OBX segments that follow it.
    for idx, segment in enumerate(segments):
        if segment.name == "OBR":
            group: list[tuple[dict, str]] = []
            for follower in segments[idx + 1:]:
                if follower.name in ("OBR", "PID", "PV1", "MSH"):
                    break
                if follower.name == "OBX":
                    mapped_obs = map_observation(follower, patient_url)
                    if mapped_obs[0] is not None and mapped_obs[1] is not None:
                        group.append((mapped_obs[0], mapped_obs[1]))
            report, report_url = map_diagnostic_report(
                segment, patient_url, [u for (_r, u) in group]
            )
            for resource, url in group:
                entries.append({"fullUrl": url, "resource": resource})
            entries.append({"fullUrl": report_url, "resource": report})

    bundle_type = "transaction" if transaction else "collection"
    bundle: dict = {
        "resourceType": "Bundle",
        "type": bundle_type,
        "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
        "entry": entries,
    }
    if transaction:
        for entry in bundle["entry"]:
            entry["request"] = {
                "method": "POST",
                "url": entry["resource"]["resourceType"],
            }
    return bundle
