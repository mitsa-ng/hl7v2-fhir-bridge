"""ORU^R01 -> FHIR R4 conversion tests. Run: python -m unittest discover -s tests"""

import json
import unittest

from hl7v2_fhir_bridge import ParseError, convert, parse_message

ORU_R01 = "\r".join([
    "MSH|^~\\&|LAB_SYSTEM|LAB_FAC|HIS_APP|HIS_FAC|20261122093000||ORU^R01|MSG00001|P|2.4",
    "PID|1||A12345678^^^NHI^TAIWAN||王^小明||19900512|M",
    "PV1|1|I|ICU^101^A",
    "OBR|1||ORD001|51990-0^Basic metabolic panel^LN|||20261122083000",
    "OBX|1|NM|718-7^Hemoglobin^LN|g/dL|13.5|g/dL|13.0-17.0|N|||F|||20261122083000",
    "OBX|2|NM|2345-7^Glucose^LN|mg/dL|95|mg/dL|70-105|N|||P|||20261122082900",
])


class ParserTests(unittest.TestCase):
    def test_msh_quirk_field_numbering(self):
        segments = parse_message(ORU_R01)
        msh = segments[0]
        self.assertEqual(msh.name, "MSH")
        self.assertEqual(msh.field(1), "|")          # MSH-1 is the separator
        self.assertEqual(msh.field_obj(2).raw, "^~\\&")  # MSH-2 raw encoding characters
        self.assertEqual(msh.field(3), "LAB_SYSTEM") # MSH-3 sending app

    def test_components_and_repetitions(self):
        segments = parse_message(ORU_R01)
        pid = segments[1]
        self.assertEqual(pid.component(3, 1), "A12345678")
        self.assertEqual(pid.component(5, 1), "王")
        self.assertEqual(pid.component(5, 2), "小明")

    def test_missing_msh_rejected(self):
        with self.assertRaises(ParseError):
            parse_message("PID|1||X")

    def test_escaped_separators_round_trip(self):
        raw = "MSH|^~\\&|S|F|R|A|20260101||ADT^A01|1|P|2.4\rPID|1||X||\\F\\pipe\\S\\hat"
        pid = parse_message(raw)[1]
        self.assertEqual(pid.field(5), "|pipe^hat")  # \F\ -> |, \S\ -> ^, first component


class ConversionTests(unittest.TestCase):
    def setUp(self):
        self.bundle = convert(parse_message(ORU_R01))

    def resources(self, resource_type):
        return [
            e["resource"]
            for e in self.bundle["entry"]
            if e["resource"]["resourceType"] == resource_type
        ]

    def full_urls(self):
        return [e["fullUrl"] for e in self.bundle["entry"]]

    def test_bundle_shape(self):
        self.assertEqual(self.bundle["resourceType"], "Bundle")
        self.assertEqual(self.bundle["type"], "collection")
        urls = self.full_urls()
        self.assertEqual(len(urls), len(set(urls)), "fullUrl must be unique (bdl-7)")

    def test_message_header(self):
        header = self.resources("MessageHeader")[0]
        self.assertEqual(header["eventCoding"]["code"], "R01")
        self.assertEqual(header["source"]["name"], "LAB_SYSTEM")
        self.assertEqual(header["destination"][0]["name"], "HIS_APP")

    def test_patient_mapping(self):
        patient = self.resources("Patient")[0]
        self.assertEqual(patient["identifier"][0]["value"], "A12345678")
        self.assertEqual(patient["identifier"][0]["system"], "https://www.nhi.gov.tw")
        self.assertEqual(patient["name"][0]["family"], "王")
        self.assertEqual(patient["name"][0]["given"], ["小明"])
        self.assertEqual(patient["gender"], "male")
        self.assertEqual(patient["birthDate"], "1990-05-12")

    def test_encounter_from_pv1(self):
        encounter = self.resources("Encounter")[0]
        self.assertEqual(encounter["class"]["code"], "IMP")  # I -> inpatient
        self.assertEqual(encounter["location"][0]["location"]["display"], "ICU 101 A")
        self.assertTrue(encounter["subject"]["reference"].startswith("urn:uuid:"))

    def test_observations(self):
        observations = self.resources("Observation")
        self.assertEqual(len(observations), 2)

        hgb = next(o for o in observations
                   if o["code"]["coding"][0]["code"] == "718-7")
        self.assertEqual(hgb["status"], "final")               # OBX-11 = F
        self.assertEqual(hgb["valueQuantity"]["value"], 13.5)
        self.assertEqual(hgb["valueQuantity"]["code"], "g/dL") # OBX-6 units
        self.assertEqual(hgb["effectiveDateTime"], "2026-11-22T08:30:00")
        self.assertEqual(hgb["referenceRange"][0]["text"], "13.0-17.0")
        self.assertEqual(hgb["code"]["coding"][0]["system"], "http://loinc.org")

        glucose = next(o for o in observations
                       if o["code"]["coding"][0]["code"] == "2345-7")
        self.assertEqual(glucose["status"], "preliminary")     # OBX-11 = P

    def test_diagnostic_report_groups_its_observations(self):
        report = self.resources("DiagnosticReport")[0]
        self.assertEqual(report["code"]["coding"][0]["code"], "51990-0")
        self.assertEqual(len(report["result"]), 2)
        urls = {e["fullUrl"] for e in self.bundle["entry"]}
        for ref in report["result"]:
            self.assertIn(ref["reference"], urls, "report must reference bundle entries")

    def test_transaction_mode_adds_requests(self):
        bundle = convert(parse_message(ORU_R01), transaction=True)
        self.assertEqual(bundle["type"], "transaction")
        for entry in bundle["entry"]:
            self.assertEqual(entry["request"]["method"], "POST")
            self.assertEqual(entry["request"]["url"], entry["resource"]["resourceType"])

    def test_deterministic_full_urls(self):
        again = convert(parse_message(ORU_R01))
        self.assertEqual(self.full_urls(), [e["fullUrl"] for e in again["entry"]])

    def test_message_without_pid_rejected(self):
        msh_only = "MSH|^~\\&|S|F|R|A|20260101||ADT^A01|1|P|2.4"
        with self.assertRaises(ValueError):
            convert(parse_message(msh_only))


class CliTests(unittest.TestCase):
    def test_cli_produces_valid_json(self):
        import subprocess, sys, tempfile, os
        with tempfile.NamedTemporaryFile("w", suffix=".hl7", delete=False, encoding="utf-8") as fh:
            fh.write(ORU_R01.replace("\r", "\n"))
            path = fh.name
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "hl7v2_fhir_bridge", path, "--pretty"],
                capture_output=True, text=True, cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            bundle = json.loads(proc.stdout)
            self.assertEqual(bundle["resourceType"], "Bundle")
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
