"""Resolve direct event-dependent contexts without changing task models."""

from collections.abc import Sequence

from src.Interfaces.ITaskModel import ITaskModel


class EffectiveContextResolver:
    """One immutable projection over a complete task population and category order."""

    def __init__(self, tasks: Sequence[ITaskModel], categories: Sequence[dict[str, str]]) -> None:
        # Keep the two best distinct receivers, so excluding an emitter itself
        # remains constant time even when many tasks share the same event.
        receivers: dict[str, list[tuple[int, int, ITaskModel, str]]] = {}
        for position, task in enumerate(tasks):
            event = task.getEventWaited()
            if task.getStatus() == "x" or not isinstance(event, str):
                continue
            context = task.getContext()
            rank = next((i for i, category in enumerate(categories)
                         if context.startswith(category["prefix"])), None)
            if rank is None:
                continue
            best = receivers.setdefault(event, [])
            if any(candidate[2] is task for candidate in best):
                continue
            best.append((rank, position, task, context))
            best.sort(key=lambda candidate: candidate[:2])
            del best[2:]

        self._receivers = receivers
        self._contexts: dict[int, str] = {}
        for task in tasks:
            context = task.getContext()
            event = task.getEventRaised()
            if task.getStatus() != "x" and isinstance(event, str):
                for _, _, receiver, inherited in receivers.get(event, []):
                    if receiver is not task:
                        context = inherited
                        break
            self._contexts[id(task)] = context

    def context(self, task: ITaskModel) -> str:
        """Return the captured effective value, or the original for an external task."""
        if id(task) in self._contexts:
            return self._contexts[id(task)]
        # Detail lookups and operation responses can carry another detached
        # instance of a task in the captured population.
        event = task.getEventRaised()
        if task.getStatus() != "x" and isinstance(event, str):
            for _, _, receiver, inherited in self._receivers.get(event, []):
                if receiver.getTaskUID() != task.getTaskUID():
                    return inherited
        return task.getContext()
