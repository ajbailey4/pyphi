# compute/__init__.py

"""
See |compute.subsystem| and |compute.network| for documentation.

Attributes:
    all_complexes: Alias for :func:`pyphi.compute.network.all_complexes`.
    ces: Alias for :func:`pyphi.compute.subsystem.ces`.
    complexes: Alias for :func:`pyphi.compute.network.complexes`.
    conceptual_info: Alias for :func:`pyphi.compute.subsystem.conceptual_info`.
    condensed: Alias for :func:`pyphi.compute.network.condensed`.
    evaluate_cut: Alias for :func:`pyphi.compute.subsystem.evaluate_cut`.
    major_complex: Alias for :func:`pyphi.compute.network.major_complex`.
    phi: Alias for :func:`pyphi.compute.subsystem.phi`.
    possible_complexes: Alias for
        :func:`pyphi.compute.network.possible_complexes`.
    sia: Alias for :func:`pyphi.compute.subsystem.sia`.
    subsystems: Alias for :func:`pyphi.compute.network.subsystems`.
"""

# pylint: disable=unused-import

from .network import (
    all_complexes,
    complexes,
    condensed,
    major_complex,
    possible_complexes,
    subsystems,
)
from .subsystem import (
    ConceptStyleSystem,
    SystemIrreducibilityAnalysisConceptStyle,
    ces,
    concept_cuts,
    conceptual_info,
    evaluate_cut,
    phi,
    sia,
    sia_concept_style,
)
