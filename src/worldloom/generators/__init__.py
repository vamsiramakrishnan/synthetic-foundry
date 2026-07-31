"""Deterministic generators.

Each module owns one slice of the world and produces only thin-waist models. None
of them calls a language model, and none reads a clock or an unseeded random
source — a world must be reproducible from its seed alone.

``names``
    Fixed name pools. A placeholder for the generative identity layer, and
    deliberately dull so nothing grows to depend on it.
``organisation``
    The entity graph: company, units, people, systems, services, personas.
``finance``
    Money, reconciling by construction rather than by later arithmetic.
``operations``
    The close sequence and the incident chain, including its wrong first answer.
``planning``
    Artifact intents and evaluation cases, both derived from facts.
"""

from . import finance, names, operations, organisation, planning

__all__ = ["finance", "names", "operations", "organisation", "planning"]
