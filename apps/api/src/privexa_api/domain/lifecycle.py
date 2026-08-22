from __future__ import annotations

from collections.abc import Mapping, Set
from enum import StrEnum
from types import MappingProxyType

from privexa_api.domain.errors import DomainLifecycleConflictError


class LifecyclePolicy[StateT: StrEnum]:
    """Explicit transition policy owned by one aggregate's lifecycle definition."""

    __slots__ = ("_allowed", "_terminal")

    def __init__(
        self,
        *,
        allowed_transitions: Mapping[StateT, Set[StateT]],
        terminal_states: Set[StateT] = frozenset(),
    ) -> None:
        allowed = {current: frozenset(targets) for current, targets in allowed_transitions.items()}
        terminal = frozenset(terminal_states)
        invalid_terminal_states = sorted(
            (state.value for state in terminal if allowed.get(state, frozenset())),
        )
        if invalid_terminal_states:
            raise ValueError(
                "terminal states cannot have outgoing transitions: "
                + ", ".join(invalid_terminal_states)
            )
        self._allowed = MappingProxyType(allowed)
        self._terminal = terminal

    def permits(self, current: StateT, target: StateT) -> bool:
        return target in self._allowed.get(current, frozenset())

    def require(self, current: StateT, target: StateT) -> None:
        if not self.permits(current, target):
            raise DomainLifecycleConflictError()

    def is_terminal(self, state: StateT) -> bool:
        return state in self._terminal
