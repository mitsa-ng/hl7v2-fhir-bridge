"""hl7v2-fhir-bridge: HL7 v2.x (ER7) to FHIR R4 converter, stdlib only."""

from .parser import ParseError, parse_message, segments_of
from .mapper import convert

__all__ = ["ParseError", "parse_message", "segments_of", "convert"]
__version__ = "0.1.0"
