# -*- coding: utf-8 -*-
# big_phi.py

import operator
import pickle
from collections import UserDict, defaultdict
from dataclasses import dataclass
from itertools import product
from typing import Generator

import ray
import scipy
from importlib_metadata import functools
from toolz.itertoolz import partition_all, unique
from tqdm.auto import tqdm

from pyphi import utils
from pyphi.cache import cache
from pyphi.models import cmp
from pyphi.models.cuts import Cut
from pyphi.subsystem import Subsystem

from . import config, models
from .compute.parallel import as_completed, init
from .compute.subsystem import sia_bipartitions as directionless_sia_bipartitions
from .direction import Direction
from .models import fmt
from .models.subsystem import CauseEffectStructure, FlatCauseEffectStructure
from .relations import Relation, Relations

# TODO
# - cache relations, compute as needed for each nonconflicting CES


class BigPhiCut(models.cuts.Cut):
    """A system cut.

    Same as a IIT 3.0 unidirectional cut, but with a Direction.
    """

    def __init__(self, direction, *args, **kwargs):
        self.direction = direction
        super().__init__(*args, **kwargs)

    def __repr__(self):
        return fmt.fmt_cut(self) + f" ({str(self.direction)[0]})"

    def to_json(self):
        return {
            "direction": self.direction,
            **super().to_json(),
        }

    @classmethod
    def from_json(cls, data):
        """Return a Cut object from a JSON-serializable representation."""
        return cls(data["direction"], data["from_nodes"], data["to_nodes"])


class CompleteCut:
    """Represents the cut that destroys all distinctions & relations."""


def is_affected_by_cut(distinction, cut):
    """Return whether the distinctions is affected by the cut."""
    # TODO(4.0) standardize logic for complete cut vs other cuts
    if isinstance(cut, CompleteCut):
        return True
    coming_from = set(cut.from_nodes) & set(distinction.mechanism)
    going_to = set(cut.to_nodes) & set(distinction.purview(cut.direction))
    return coming_from and going_to


def unaffected_distinctions(ces, cut):
    """Return the CES composed of distinctions that are not affected by the given cut."""
    # Special case for empty CES
    if isinstance(cut, CompleteCut):
        return CauseEffectStructure([], subsystem=ces.subsystem)
    return CauseEffectStructure(
        [distinction for distinction in ces if not is_affected_by_cut(distinction, cut)]
    )


def unaffected_relations(ces, relations):
    """Yield relations that not supported by the given CES."""
    # Special case for empty relations
    if not ces:
        return Relations([])
    # TODO use lattice data structure for efficiently finding the union of the
    # lower sets of lost distinctions
    ces = FlatCauseEffectStructure(ces)
    return Relations(
        [
            relation
            for relation in relations
            if all(distinction in ces for distinction in relation.relata)
        ]
    )


def sia_partitions(node_indices, node_labels):
    """Yield all system partitions."""
    # TODO(4.0) configure
    for cut in directionless_sia_bipartitions(node_indices, node_labels):
        for direction in Direction.both():
            yield BigPhiCut(
                direction, cut.from_nodes, cut.to_nodes, node_labels=cut.node_labels
            )


@cache(cache={}, maxmem=None)
def number_of_possible_relations_with_overlap(n, k):
    """Return the number of possible relations with overlap of size k."""
    return (
        (-1) ** (k - 1)
        * scipy.special.comb(n, k)
        * (2 ** (2 ** (n - k + 1)) - 1 - 2 ** (n - k + 1))
    )


@cache(cache={}, maxmem=None)
def optimum_sum_small_phi_relations(n):
    """Return the 'best possible' sum of small phi for relations."""
    # \sum_{k=1}^{n} (size of purview) * (number of relations with that purview size)
    return sum(
        k * number_of_possible_relations_with_overlap(n, k) for k in range(1, n + 1)
    )


@cache(cache={}, maxmem=None)
def optimum_sum_small_phi_distinctions_one_direction(n):
    """Return the 'best possible' sum of small phi for distinctions in one direction"""
    # \sum_{k=1}^{n} k(n choose k)
    return (2 / n) * (2 ** n)


@cache(cache={}, maxmem=None)
def optimum_sum_small_phi(n):
    """Return the 'best possible' sum of small phi for the system."""
    # Double distinction term for cause & effect sides
    distinction_term = 2 * optimum_sum_small_phi_distinctions_one_direction(n)
    relation_term = optimum_sum_small_phi_relations(n)
    return distinction_term + relation_term


def _requires_relations(func):
    @functools.wraps(func)
    def wrapper(self, *args, **kwargs):
        # Get relations from Ray if they're remote
        if isinstance(self.relations, ray.ObjectRef):
            self.relations = ray.get(self.relations)
        # Filter relations if flag is set
        if self.requires_filter:
            self.filter_relations()
        # Realize relations if they're a generator
        if isinstance(self.relations, Generator):
            self.relations = Relations(self.relations)
        return func(self, *args, **kwargs)

    return wrapper


class PhiStructure(cmp.Orderable):
    def __init__(self, distinctions, relations, requires_filter=False):
        if not isinstance(distinctions, CauseEffectStructure):
            raise ValueError("distinctions must be a CauseEffectStructure")
        if isinstance(distinctions, FlatCauseEffectStructure):
            distinctions = distinctions.unflatten()
        self.requires_filter = requires_filter
        self.distinctions = distinctions
        self.relations = relations
        self._system_intrinsic_information = None
        self._sum_phi_distinctions = None
        self._sum_phi_relations = None
        self._selectivity = None
        if distinctions:
            # TODO improve this
            self._substrate_size = len(distinctions.subsystem)

    def order_by(self):
        return self.system_intrinsic_information()

    def __eq__(self, other):
        return cmp.general_eq(
            self,
            other,
            [
                "distinctions",
                "relations",
            ],
        )

    def filter_relations(self):
        """Update relations so that only those supported by distinctions remain.

        Modifies the relations on this object in-place.
        """
        self.relations = unaffected_relations(self.distinctions, self.relations)
        self.requires_filter = False

    def sum_phi_distinctions(self):
        if self._sum_phi_distinctions is None:
            self._sum_phi_distinctions = sum(self.distinctions.phis)
        return self._sum_phi_distinctions

    @_requires_relations
    def sum_phi_relations(self):
        if self._sum_phi_relations is None:
            self._sum_phi_relations = sum(self.relations.phis)
        return self._sum_phi_relations

    def selectivity(self):
        if self._selectivity is None:
            self._selectivity = (
                self.sum_phi_distinctions() + self.sum_phi_relations()
            ) / optimum_sum_small_phi(self._substrate_size)
        return self._selectivity

    @_requires_relations
    def realize(self):
        """Instantiate lazy properties."""
        # Currently this is just a hook to force _requires_relations to do its
        # work. Also very Zen.
        return self

    def partition(self, cut):
        """Return a PartitionedPhiStructure with the given cut."""
        return PartitionedPhiStructure(self, cut, requires_filter=self.requires_filter)

    def system_intrinsic_information(self):
        """Return the system intrinsic information.

        This is the phi of the system with respect to the complete partition.
        """
        if self._system_intrinsic_information is None:
            self._system_intrinsic_information = self.partition(CompleteCut()).phi()
        return self._system_intrinsic_information

    def to_pickle(self, path):
        with open(path, mode="wb") as f:
            pickle.dump(self.to_json(), f)
        return path

    @classmethod
    def read_pickle(cls, path):
        with open(path, mode="rb") as f:
            data = pickle.load(f)
        # TODO(4.0) change to Relations class when available
        distinctions = data["distinctions"]
        distinctions.subsystem = data["subsystem"]
        relations = [
            Relation.from_indirect_json(data["subsystem"], distinctions, relation)
            for relation in data["relations"]
        ]
        return cls(distinctions.unflatten(), relations)

    def to_json(self):
        distinctions = FlatCauseEffectStructure(self.distinctions)
        indirect_relations = [
            relation.to_indirect_json(distinctions) for relation in self.relations
        ]
        # TODO(4.0) remove this hack
        subsystem = self.distinctions.subsystem
        return {
            "subsystem": subsystem,
            "distinctions": distinctions,
            "relations": indirect_relations,
        }


class PartitionedPhiStructure(PhiStructure):
    def __init__(self, phi_structure, cut, requires_filter=False):
        # We need to realize the underlying PhiStructure in case
        # distinctions/relations are generators which may later become exhausted
        self.unpartitioned_phi_structure = phi_structure.realize()
        super().__init__(
            self.unpartitioned_phi_structure.distinctions,
            self.unpartitioned_phi_structure.relations,
            # Relations should have been filtered when `.realize()` was called
            requires_filter=False,
        )
        self.cut = cut
        # Lift values from unpartitioned PhiStructure
        for attr in [
            "_system_intrinsic_information",
            "_substrate_size",
            "_sum_phi_distinctions",
            "_sum_phi_relations",
            "_selectivity",
        ]:
            setattr(
                self,
                attr,
                getattr(self.unpartitioned_phi_structure, attr),
            )
        self._partitioned_distinctions = None
        self._partitioned_relations = None
        self._sum_phi_partitioned_distinctions = None
        self._sum_phi_partitioned_relations = None
        self._informativeness = None

    def order_by(self):
        return self.phi()

    def __eq__(self, other):
        return super().__eq__(other) and cmp.general_eq(
            self,
            other,
            [
                "phi",
                "cut",
                "partitioned_distinctions",
                "partitioned_relations",
            ],
        )

    def __bool__(self):
        """A |SystemIrreducibilityAnalysis| is ``True`` if it has |big_phi > 0|."""
        return not utils.eq(self.phi(), 0)

    def partitioned_distinctions(self):
        if self._partitioned_distinctions is None:
            self._partitioned_distinctions = unaffected_distinctions(
                self.distinctions, self.cut
            )
        return self._partitioned_distinctions

    @_requires_relations
    def partitioned_relations(self):
        if self._partitioned_relations is None:
            self._partitioned_relations = unaffected_relations(
                self.partitioned_distinctions(), self.relations
            )
        return self._partitioned_relations

    def sum_phi_partitioned_distinctions(self):
        if self._sum_phi_partitioned_distinctions is None:
            self._sum_phi_partitioned_distinctions = sum(
                self.partitioned_distinctions().phis
            )
        return self._sum_phi_partitioned_distinctions

    def sum_phi_partitioned_relations(self):
        if self._sum_phi_partitioned_relations is None:
            self._sum_phi_partitioned_relations = sum(self.partitioned_relations().phis)
            # Remove reference to the (heavy and rather redundant) lists of
            # partitioned distinctions & relations under the assumption we won't
            # need them again, since most PartitionedPhiStructures will be used
            # only once, during SIA calculation
            self._partitioned_distinctions = None
            self._partitioned_relations = None
        return self._sum_phi_partitioned_relations

    # TODO use only a single pass through the distinctions / relations?
    def informativeness(self):
        if self._informativeness is None:
            distinction_term = (
                self.sum_phi_distinctions() - self.sum_phi_partitioned_distinctions()
            )
            relation_term = (
                self.sum_phi_relations() - self.sum_phi_partitioned_relations()
            )
            self._informativeness = distinction_term + relation_term
        return self._informativeness

    def phi(self):
        return self.selectivity() * self.informativeness()


def selectivity(phi_structure):
    """Return the selectivity of the PhiStructure."""
    return phi_structure.selectivity()


def informativeness(partitioned_phi_structure):
    """Return the informativeness of the PartitionedPhiStructure."""
    return partitioned_phi_structure.informativeness()


def phi(partitioned_phi_structure):
    """Return the phi of the PartitionedPhiStructure."""
    return partitioned_phi_structure.phi()


# TODO add rich methods, comparisons, etc.
@dataclass
class SystemIrreducibilityAnalysis(cmp.Orderable):
    subsystem: Subsystem
    phi_structure: PhiStructure
    partitioned_phi_structure: PartitionedPhiStructure
    cut: Cut
    selectivity: float
    informativeness: float
    phi: float

    _sia_attributes = ["phi", "phi_structure", "partitioned_phi_structure", "subsystem"]

    def order_by(self):
        return [self.phi, len(self.subsystem), self.subsystem.node_indices]

    def __eq__(self, other):
        return cmp.general_eq(self, other, self._sia_attributes)

    def __bool__(self):
        """A |SystemIrreducibilityAnalysis| is ``True`` if it has |big_phi > 0|."""
        return not utils.eq(self.phi, 0)

    def __hash__(self):
        return hash(
            (
                self.phi,
                self.ces,
                self.partitioned_ces,
                self.subsystem,
                self.cut_subsystem,
            )
        )


# TODO(4.0) rename Cut -> Partition
def evaluate_cut(subsystem, phi_structure, cut):
    partitioned_phi_structure = phi_structure.partition(cut)
    return SystemIrreducibilityAnalysis(
        subsystem=subsystem,
        phi_structure=phi_structure,
        partitioned_phi_structure=partitioned_phi_structure,
        cut=partitioned_phi_structure.cut,
        selectivity=partitioned_phi_structure.selectivity(),
        informativeness=partitioned_phi_structure.informativeness(),
        phi=partitioned_phi_structure.phi(),
    )


def has_nonspecified_elements(subsystem, distinctions):
    """Return whether any elements are not specified by a purview in both
    directions."""
    elements = set(subsystem.node_indices)
    specified = {direction: set() for direction in Direction.both()}
    for distinction in distinctions:
        for direction in Direction.both():
            specified[direction].update(set(distinction.purview(direction)))
    return any(elements - _specified for _specified in specified.values())


def has_no_spanning_specification(subsystem, distinctions):
    """Return whether the system can be separated into disconnected components.

    Here disconnected means that there is no "spanning specification"; some
    subset of elements only specifies themselves and is not specified by any
    other subset.
    """
    # TODO
    return False


REDUCIBILITY_CHECKS = [
    has_nonspecified_elements,
    has_no_spanning_specification,
]


class CompositionalState(UserDict):
    """A mapping from purviews to states."""


def is_congruent(distinction, state):
    """Return whether (any of) the (tied) specified state(s) is the given one."""
    return any(state == tuple(specified) for specified in distinction.specified_state)


def filter_ces(ces, direction, compositional_state):
    """Return only the distinctions consistent with the given compositional state."""
    for distinction in ces:
        try:
            if distinction.direction == direction and is_congruent(
                distinction,
                compositional_state[distinction.purview],
            ):
                yield distinction
        except KeyError:
            pass


def _nonconflicting_mice_set(purview_to_mice):
    """Return all combinations where each purview is mapped to a single mechanism."""
    return map(frozenset, product(*purview_to_mice.values()))


# TODO(4.0) parallelize somehow?
def all_nonconflicting_distinction_sets(distinctions):
    """Return all possible conflict-free distinction sets."""
    if isinstance(distinctions, FlatCauseEffectStructure):
        raise ValueError("Expected CauseEffectStructure; got FlatCauseEffectStructure")
    # Map mechanisms to their distinctions for later fast retrieval
    mechanism_to_distinction = {
        frozenset(distinction.mechanism): distinction for distinction in distinctions
    }
    # Map purviews to mechanisms that specify them, on both cause and effect sides
    purview_to_mechanism = {
        direction: defaultdict(list) for direction in Direction.both()
    }
    for mechanism, distinction in mechanism_to_distinction.items():
        for direction, mapping in purview_to_mechanism.items():
            # Cast mechanism to set so we can take intersections later
            mapping[distinction.purview(direction)].append(mechanism)
    # Generate nonconflicting sets of mechanisms on both cause and effect sides
    nonconflicting_causes, nonconflicting_effects = tuple(
        _nonconflicting_mice_set(purview_to_mechanism[direction])
        for direction in Direction.both()
    )
    # Ensure nonconflicting sets are unique
    nonconflicting_mechanisms = unique(
        # Take only distinctions that are nonconflicting on both sides
        cause_mechanisms & effect_mechanisms
        # Pair up nonconflicting sets from either side
        for cause_mechanisms, effect_mechanisms in product(
            nonconflicting_causes, nonconflicting_effects
        )
    )
    for mechanisms in nonconflicting_mechanisms:
        # Convert to actual MICE objects
        yield CauseEffectStructure(
            map(mechanism_to_distinction.get, mechanisms),
            subsystem=distinctions.subsystem,
        )


# TODO put in utils
def extremum_with_short_circuit(
    seq,
    value_func=lambda item: item.phi,
    cmp=operator.lt,
    initial=float("inf"),
    shortcircuit_value=0,
    shortcircuit_callback=None,
):
    """Return the extreme value, optionally shortcircuiting."""
    extreme_item = None
    extreme_value = initial
    for item in seq:
        value = value_func(item)
        if value == shortcircuit_value:
            try:
                shortcircuit_callback()
            except TypeError:
                pass
            return item
        if cmp(value, extreme_value):
            extreme_value = value
            extreme_item = item
    return extreme_item


@ray.remote
def _evaluate_cuts(subsystem, phi_structure, cuts):
    return extremum_with_short_circuit(
        (evaluate_cut(subsystem, phi_structure, cut) for cut in cuts),
        cmp=operator.lt,
        initial=float("inf"),
        shortcircuit_value=0,
    )


def _null_sia(subsystem, phi_structure):
    if not subsystem.cut.is_null:
        raise ValueError("subsystem must have no cut")
    partitioned_phi_structure = phi_structure.partition(subsystem.cut)
    return SystemIrreducibilityAnalysis(
        subsystem=subsystem,
        phi_structure=phi_structure,
        partitioned_phi_structure=partitioned_phi_structure,
        cut=partitioned_phi_structure.cut,
        selectivity=None,
        informativeness=None,
        phi=0.0,
    )


def is_trivially_reducible(subsystem, phi_structure):
    # TODO(4.0) realize phi structure here if anything requires relations?
    return any(
        check(subsystem, phi_structure.distinctions) for check in REDUCIBILITY_CHECKS
    )


# TODO configure
DEFAULT_CUT_CHUNKSIZE = 500
DEFAULT_PHI_STRUCTURE_CHUNKSIZE = 50


# TODO document args
def evaluate_phi_structure(
    subsystem,
    phi_structure,
    check_trivial_reducibility=True,
    chunksize=DEFAULT_CUT_CHUNKSIZE,
):
    """Analyze the irreducibility of a PhiStructure."""
    # Realize the PhiStructure before distributing tasks
    phi_structure.realize()

    if check_trivial_reducibility and is_trivially_reducible(subsystem, phi_structure):
        return _null_sia(subsystem, phi_structure)

    tasks = [
        _evaluate_cuts.remote(
            subsystem,
            phi_structure,
            cuts,
        )
        for cuts in partition_all(
            chunksize, sia_partitions(subsystem.cut_indices, subsystem.cut_node_labels)
        )
    ]
    return extremum_with_short_circuit(
        as_completed(tasks),
        cmp=operator.lt,
        initial=float("inf"),
        shortcircuit_value=0,
        shortcircuit_callback=lambda: [ray.cancel(task) for task in tasks],
    )


@ray.remote
def _evaluate_phi_structures(
    subsystem,
    phi_structures,
    **kwargs,
):
    return max(
        evaluate_phi_structure(subsystem, phi_structure, **kwargs)
        for phi_structure in phi_structures
    )


def _max_system_intrinsic_information(phi_structures):
    return max(
        phi_structures,
        key=lambda phi_structure: phi_structure.system_intrinsic_information(),
    )


_remote_max_system_intrinsic_information = ray.remote(_max_system_intrinsic_information)


# TODO refactor into a pattern
def find_maximal_compositional_state(
    phi_structures,
    chunksize=DEFAULT_PHI_STRUCTURE_CHUNKSIZE,
    progress=True,
):
    print("Finding maximal compositional state")
    tasks = [
        _remote_max_system_intrinsic_information.remote(chunk)
        for chunk in tqdm(
            partition_all(chunksize, phi_structures), desc="Submitting tasks"
        )
    ]
    print("Done submitting tasks")
    results = as_completed(tasks)
    if progress:
        results = tqdm(results, total=len(tasks))
    return _max_system_intrinsic_information(results)


# TODO allow choosing whether you provide precomputed distinctions
# (sometimes faster to compute as you go if many distinctions are killed by conflicts)
# TODO document args
def sia(
    subsystem,
    all_distinctions,
    all_relations,
    phi_structures=None,
    check_trivial_reducibility=True,
    chunksize=DEFAULT_PHI_STRUCTURE_CHUNKSIZE,
    cut_chunksize=DEFAULT_CUT_CHUNKSIZE,
    filter_relations=False,
    progress=True,
):
    """Analyze the irreducibility of a system."""
    # First check that the entire set of distinctions/relations is not trivially reducible
    # (since then all subsets must be)
    full_phi_structure = PhiStructure(all_distinctions, all_relations)
    if check_trivial_reducibility and is_trivially_reducible(
        subsystem, full_phi_structure
    ):
        print("Returning trivially-reducible SIA")
        return _null_sia(subsystem, full_phi_structure)

    # Assume that phi structures passed by the user don't need to have their
    # relations filtered
    if phi_structures is None:
        filter_relations = True
        # Broadcast relations to workers
        all_relations = ray.put(all_relations)
        print("Done putting relations")
        phi_structures = (
            PhiStructure(
                distinctions,
                all_relations,
                requires_filter=filter_relations,
            )
            for distinctions in all_nonconflicting_distinction_sets(all_distinctions)
        )

    if config.IIT_VERSION == "maximal-state-first":
        maximal_compositional_state = find_maximal_compositional_state(
            phi_structures,
            chunksize=chunksize,
            progress=progress,
        )
        print("Evaluating maximal compositional state")
        return evaluate_phi_structure(
            subsystem,
            maximal_compositional_state,
            check_trivial_reducibility=check_trivial_reducibility,
            chunksize=cut_chunksize,
        )
    else:
        # Broadcast subsystem object to workers
        subsystem = ray.put(subsystem)
        print("Done putting subsystem")

        print("Evaluating all compositional states")
        tasks = [
            _evaluate_phi_structures.remote(
                subsystem,
                chunk,
                check_trivial_reducibility=check_trivial_reducibility,
                chunksize=cut_chunksize,
            )
            for chunk in tqdm(
                partition_all(chunksize, phi_structures), desc="Submitting tasks"
            )
        ]
        print("Done submitting tasks")
        results = as_completed(tasks)
        if progress:
            results = tqdm(results, total=len(tasks))
        return max(results)
