# hl7v2-fhir-bridge

Convert HL7 v2.x ER7 messages (ORU^R01 lab focus) into FHIR R4 Bundles.
Python standard library only: no dependencies, no build, runs anywhere.

Built for the classic hospital integration problem: lab systems still speak
pipe-and-hat v2 while everything downstream wants FHIR. This bridge parses
the wire format properly (delimiters from MSH-2, repetitions, escape
sequences) and emits resources that validate against R4 invariants.

## Segment coverage

| v2 segment | FHIR R4 resource | Key fields |
|---|---|---|
| MSH | MessageHeader | 9.2 event code, 3/5 source and destination apps |
| PID | Patient | 3 identifier (with assigning authority), 5 name, 7 birthDate, 8 gender |
| PV1 | Encounter | 2 patient class → v3 ActCode, 3 location display |
| OBR | DiagnosticReport | 4 code, 7 effective, 25 status; groups its OBXs into `result` |
| OBX | Observation | 3 code (LOINC aware), 2+5+6 typed value, 7 referenceRange, 11 status, 14 effective |

Code systems recognized via table 0396 subset: LOINC (`LN`), UCUM, SNOMED,
plus a slot for Taiwan NHI identifiers.

## Usage

```sh
python3 -m hl7v2_fhir_bridge message.hl7 --pretty          # collection Bundle
python3 -m hl7v2_fhir_bridge message.hl7 --transaction     # + entry.request POST
cat message.hl7 | python3 -m hl7v2_fhir_bridge -
```

Bundle entries use deterministic `urn:uuid:` fullUrls (UUIDv5 over the
message's own identifiers), so repeated conversions of the same message
produce byte-stable references.

## Mapping decisions worth knowing

- OBX-11 status follows v2 table 0085 (F→final, P→preliminary, C→corrected,
  D→entered-in-error); anything unmapped lands on `unknown`, never a guess
- OBX-2 `NM` becomes `valueQuantity` with UCUM-coded units from OBX-6;
  everything else becomes `valueString`
- Reference ranges stay `text` (parsing "13.0-17.0" into low/high is easy to
  get wrong with qualifier forms, so it is explicit future work)
- PV1-2 `I/E/O/P` map to ActCode IMP/EMER/AMB/PRENC; unknown classes fall
  back to AMB with the original code preserved as the display
- Escape sequences (`\F\`, `\S\`, `\T\`, `\R\`, `\E\`) are unescaped;
  subcomponents flatten to `/`

## Cross-validation with fhir-lens

The output checks clean under [fhir-lens](../fhir-lens), including
transaction-mode invariants:

```sh
python3 -m hl7v2_fhir_bridge demo.hl7 --transaction > bundle.json
node ../fhir-lens/bin/fhir-lens.ts validate bundle.json --expect Bundle
# resourceType: Bundle
# valid:       true
```

## Tests

```sh
python3 -m unittest discover -s tests   # 14 tests
```

## Roadmap

- ORU^R01 NTE segments → Observation.note
- MDM^T02 document messages → DocumentReference
- z-segment passthrough captured in extensions
- Reference range low/high parsing

## License

MIT
