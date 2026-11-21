"""ER7 (pipe-and-hat) parser for HL7 v2.x messages.

Model: a message is a list of segments; a segment is a list of fields
(1-based index, including the MSH-1 quirk); a field holds repetitions, each
a list of components. Subcomponents are flattened into component text with
"/" as the display separator. Delimiters come from the message's own MSH-2.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field


class ParseError(ValueError):
    """Raised when the input cannot be read as an HL7 v2 ER7 message."""


@dataclass
class Field:
    repetitions: list[list[str]] = dc_field(default_factory=list)
    raw: str = ""

    def value(self) -> str:
        """First component of the first repetition (the scalar field value)."""
        if not self.repetitions or not self.repetitions[0]:
            return ""
        return self.repetitions[0][0]

    def component(self, n: int) -> str:
        """1-based component of the first repetition."""
        if not self.repetitions:
            return ""
        first = self.repetitions[0]
        if 1 <= n <= len(first):
            return first[n - 1]
        return ""


@dataclass
class Segment:
    name: str
    fields: list[Field] = dc_field(default_factory=list)

    def field(self, n: int) -> str:
        """1-based field value: field(3) is MSH-3 on an MSH segment."""
        if 1 <= n <= len(self.fields):
            return self.fields[n - 1].value()
        return ""

    def field_obj(self, n: int) -> Field:
        if 1 <= n <= len(self.fields):
            return self.fields[n - 1]
        return Field()

    def component(self, field_n: int, comp_n: int) -> str:
        return self.field_obj(field_n).component(comp_n)


def _unescape(text: str, esc: str) -> str:
    if not text or esc == "":
        return text
    for marker, ch in (
        (f"{esc}F{esc}", "|"),
        (f"{esc}S{esc}", "^"),
        (f"{esc}T{esc}", "&"),
        (f"{esc}R{esc}", "~"),
        (f"{esc}E{esc}", esc),
    ):
        text = text.replace(marker, ch)
    return text


def parse_message(raw: str) -> list[Segment]:
    """Parse an ER7 message into segments. Raises ParseError without MSH."""
    normalized = raw.replace("\r\n", "\r").replace("\n", "\r")
    lines = [line for line in normalized.split("\r") if line.strip()]

    if not lines or not lines[0].startswith("MSH"):
        raise ParseError("message must start with an MSH segment")

    header = lines[0]
    if len(header) < 8:
        raise ParseError("MSH segment too short to carry encoding characters")
    field_sep = header[3]
    special = header[4:8]
    comp_sep, rep_sep, esc, sub_sep = special[0], special[1], special[2], special[3]

    def parse_field(raw_field: str) -> Field:
        reps: list[list[str]] = []
        for repetition in raw_field.split(rep_sep):
            components = [
                _unescape(comp.replace(sub_sep, "/"), esc)
                for comp in repetition.split(comp_sep)
            ]
            reps.append(components)
        return Field(repetitions=reps, raw=raw_field)

    segments: list[Segment] = []
    for line in lines:
        parts = line.split(field_sep)
        if parts[0] == "MSH":
            # MSH-1 is the field separator itself; parts[1] is MSH-2.
            raw_fields = [field_sep] + parts[1:]
        else:
            raw_fields = parts[1:]
        segments.append(
            Segment(name=parts[0], fields=[parse_field(f) for f in raw_fields])
        )
    return segments


def segments_of(segments: list[Segment], name: str) -> list[Segment]:
    return [seg for seg in segments if seg.name == name]
