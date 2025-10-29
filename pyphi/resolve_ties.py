# resolve_ties.py
"""Resolve ties between IIT objects."""

from itertools import tee

from .conf import config, fallback
from .registry import Registry
from .utils import all_maxima, all_minima, NO_DEFAULT, iter_with_default


class PhiObjectTieResolutionRegistry(Registry):
    """Storage for functions for resolving ties among phi-objects."""

    desc = "functions for resolving ties among phi-objects"


phi_object_tie_resolution_strategies = PhiObjectTieResolutionRegistry()


@phi_object_tie_resolution_strategies.register("PURVIEW_SIZE")
def _(m):
    return len(m.purview)


@phi_object_tie_resolution_strategies.register("NEGATIVE_PURVIEW_SIZE")
def _(m):
    return -len(m.purview)


@phi_object_tie_resolution_strategies.register("PHI")
def _(m):
    return m.phi


@phi_object_tie_resolution_strategies.register("NEGATIVE_PHI")
def _(m):
    return -m.phi


@phi_object_tie_resolution_strategies.register("NORMALIZED_PHI")
def _(m):
    return m.normalized_phi


@phi_object_tie_resolution_strategies.register("NEGATIVE_NORMALIZED_PHI")
def _(m):
    return -m.normalized_phi


@phi_object_tie_resolution_strategies.register("NONE")
def _(m):
    raise NotImplementedError(
        'tie resolution strategy "NONE" should never be called; '
        "it must be special-cased in the resolve() function"
    )


def _strategies_to_key_function(strategies):
    """Convert a tie resolution strategy to a key function."""
    if isinstance(strategies, str):
        # Allow a single strategy to be specified as a bare string
        strategies = [strategies]
    return lambda obj: tuple(
        phi_object_tie_resolution_strategies[s](obj) for s in strategies
    )


def resolve(objects, strategy, operation, default=NO_DEFAULT):
    """
    Filter phi-objects according to a strategy.

    Args:
        objects (Iterable): Sequence of phi-objects.
        strategy (str | list[str]): Name(s) of tie-resolution strategy(ies)
            to determine comparison order.
        operation (callable): Function selecting extrema (e.g. `all_maxima` or `all_minima`).
        default: Optional default value if `objects` is empty.

    Yields:
        The object(s) achieving the extremal value under the given strategy.
    """
    if strategy == "NONE":
        yield from iter_with_default(objects, default=default)
        return

    get_key = _strategies_to_key_function(strategy)
    ties = operation(objects, get_key=get_key, default=default)
    yield from iter_with_default(ties, default=default)


def states(rias, strategy=None, **kwargs):
    """Resolve ties among states (RIAs).

    Controlled by the STATE_TIE_RESOLUTION configuration option.
    """
    strategy = fallback(strategy, config.STATE_TIE_RESOLUTION)
    return resolve(rias, strategy, operation=all_maxima, **kwargs)


def partitions(mips, strategy=None, **kwargs):
    """Resolve ties among mechanism partitions (MIPs).

    Controlled by the MIP_TIE_RESOLUTION configuration option.
    """
    strategy = fallback(strategy, config.MIP_TIE_RESOLUTION)
    return resolve(mips, strategy, operation=all_minima, **kwargs)


def purviews(mice, strategy=None, **kwargs):
    """Resolve ties among purviews (MICEs).

    Controlled by the PURVIEW_TIE_RESOLUTION configuration option.
    """
    strategy = fallback(strategy, config.PURVIEW_TIE_RESOLUTION)
    yield from resolve(mice, strategy, operation=all_maxima, **kwargs)
