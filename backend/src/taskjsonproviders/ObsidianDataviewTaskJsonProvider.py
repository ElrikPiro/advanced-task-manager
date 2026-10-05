import re
from collections.abc import Mapping

from src.Utils import TaskJsonListType, TaskJsonType
from ..Interfaces.ITaskJsonProvider import ITaskJsonProvider
from ..Interfaces.IFileBroker import IFileBroker, FileRegistry, VaultRegistry
from ..taskmodels.TaskIdentity import validate_task_id
from ..taskproviders.TaskIdentityErrors import InvalidTaskIdentityError
from ..MutationCoordinator import MutationCoordinator


class ObsidianDataviewTaskJsonProvider(ITaskJsonProvider):

    _TASK_LINE = re.compile(r"^\s*-\s+\[([ xX])\]\s*(.*)$")
    _TASK_METADATA = re.compile(r"\[([^\]:]+)::\s*([^\]]*)\]")

    def __init__(
        self,
        fileBroker: IFileBroker,
        mutation_coordinator: MutationCoordinator | None = None,
    ) -> None:
        self.fileBroker = fileBroker
        self.mutation_coordinator = mutation_coordinator
        if self.mutation_coordinator is None:
            inherited_coordinator = getattr(fileBroker, "mutation_coordinator", None)
            if isinstance(inherited_coordinator, MutationCoordinator):
                self.mutation_coordinator = inherited_coordinator

    def getJson(self) -> TaskJsonType:
        retval = self.fileBroker.readFileContentJson(FileRegistry.OBSIDIAN_TASKS_JSON)
        if not isinstance(retval, dict):
            raise TypeError("Obsidian task JSON must contain an object at the top level")
        tasks = retval.get("tasks", [])
        if not isinstance(tasks, list):
            raise TypeError("Obsidian task JSON must contain a task list")

        # The materialized view may not yet expose an ID tag. Read that identity
        # from the current Markdown line so edits keep the identifier already
        # stored in the vault.
        markdown_ids = self._read_markdown_ids()
        result = dict(retval)
        result_tasks: TaskJsonListType = []
        for raw_task in tasks:
            if not isinstance(raw_task, dict):
                raise TypeError("Obsidian task entries must be objects")
            task = dict(raw_task)
            declared_id = validate_task_id(task["id"]) if "id" in task else None
            markdown_id = self._id_at_task_location(task, markdown_ids)
            if markdown_id is not None:
                if declared_id is not None and declared_id != markdown_id:
                    raise InvalidTaskIdentityError("The task view and Markdown line declare conflicting identifiers")
                task["id"] = markdown_id
            elif declared_id is not None:
                task["id"] = declared_id
            result_tasks.append(task)
        result["tasks"] = result_tasks
        return result

    def _read_markdown_ids(self) -> dict[tuple[str, int], str]:
        identities: dict[tuple[str, int], str] = {}
        for relative_path, _ in self.fileBroker.getVaultFiles(VaultRegistry.OBSIDIAN):
            if not relative_path.lower().endswith(".md"):
                continue
            path = relative_path.replace("\\", "/")
            lines = self.fileBroker.getVaultFileLines(VaultRegistry.OBSIDIAN, relative_path)
            for line_number, line in enumerate(lines):
                task_match = self._TASK_LINE.match(line)
                if task_match is None:
                    continue
                declared_ids = [
                    validate_task_id(match.group(2).strip())
                    for match in self._TASK_METADATA.finditer(task_match.group(2))
                    if match.group(1).strip() == "id"
                ]
                if len(set(declared_ids)) > 1:
                    raise InvalidTaskIdentityError("A Markdown task declares conflicting identifiers")
                if declared_ids:
                    identities[(path, line_number)] = declared_ids[0]
        return identities

    @staticmethod
    def _id_at_task_location(task: Mapping[str, object], markdown_ids: dict[tuple[str, int], str]) -> str | None:
        path = task.get("file")
        line = task.get("line")
        if not isinstance(path, str) or not isinstance(line, (str, int)) or isinstance(line, bool):
            return None
        try:
            line_number = int(line)
        except (TypeError, ValueError):
            return None
        return markdown_ids.get((path.replace("\\", "/"), line_number))

    def discover(self) -> TaskJsonType:
        # Dataview already materializes its current task view in the source
        # JSON; it has no additional reconciliation to perform.
        return self.getJson()
        
    def saveJson(self, json: TaskJsonType) -> None:
        # do nothing
        pass
