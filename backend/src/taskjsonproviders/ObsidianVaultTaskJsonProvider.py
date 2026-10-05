import re
import math

from src.Utils import ProjectJsonListType, TaskDiscoveryPolicies, TaskJsonListType, TaskJsonType
from ..wrappers.TimeManagement import TimePoint
from ..Interfaces.ITaskJsonProvider import ITaskJsonProvider, VALID_PROJECT_STATUS
from ..Interfaces.IFileBroker import IFileBroker, VaultRegistry
from ..taskmodels.TaskIdentity import fallback_task_id, validate_task_id
from ..taskproviders.TaskIdentityErrors import AmbiguousTaskIdentityError, InvalidTaskIdentityError
from ..MutationCoordinator import MutationCoordinator


class ObsidianVaultTaskJsonProvider(ITaskJsonProvider):

    _TASK_LINE = re.compile(r"^\s*-\s+\[([ xX])\]\s*(.*)$")
    _TASK_METADATA = re.compile(r"\[([^\]:]+)::\s*([^\]]*)\]")

    def __init__(
        self,
        fileBroker: IFileBroker,
        policies: TaskDiscoveryPolicies,
        mutation_coordinator: MutationCoordinator | None = None,
    ):
        self.__fileBroker = fileBroker
        self.__policies = policies
        self.mutation_coordinator = mutation_coordinator
        if self.mutation_coordinator is None:
            inherited_coordinator = getattr(fileBroker, "mutation_coordinator", None)
            if isinstance(inherited_coordinator, MutationCoordinator):
                self.mutation_coordinator = inherited_coordinator

    def getJson(self) -> TaskJsonType:
        """Read and parse vault data without creating or changing task files."""
        task_list: TaskJsonListType = []
        project_list: ProjectJsonListType = []

        vaultFiles = [
            file for file in self.__fileBroker.getVaultFiles(VaultRegistry.OBSIDIAN)
            if file[0].lower().endswith(".md")
        ]
        for file in vaultFiles:
            self.__process_task_file(file, task_list, project_list)

        return {
            "tasks": task_list,
            "projects": project_list
        }

    def parseTaskFile(self, relative_path: str, lines: list[str]) -> list[dict[str, str]]:
        """Parse one supplied Markdown snapshot without performing file I/O."""
        task_list: TaskJsonListType = []
        file_header = self.__getFileHeader(lines)
        for line_number, line in self.__getFileTaskLines(lines, file_header):
            task = self.__getTaskDictFromLine(line, relative_path, line_number, file_header)
            if task["valid"] == "True":
                self.__update_or_append_task(task, task_list)
        return task_list

    def discover(self) -> TaskJsonType:
        if self.mutation_coordinator is not None:
            return self.mutation_coordinator.run_or_inline(self.__discover)
        return self.__discover()

    def __discover(self) -> TaskJsonType:
        """Persist a default next action in each uncovered open project."""
        vaultFiles = [
            file for file in self.__fileBroker.getVaultFiles(VaultRegistry.OBSIDIAN)
            if file[0].lower().endswith(".md")
        ]
        known_task_ids: set[str] = set()
        for initial_path, _ in vaultFiles:
            known_task_ids.update(
                self.__task_ids_from_lines(
                    self.__fileBroker.getVaultFileLines(VaultRegistry.OBSIDIAN, initial_path),
                    initial_path,
                )
            )

        for vault_file in vaultFiles:
            relative_path = vault_file[0]
            lines = self.__fileBroker.getVaultFileLines(VaultRegistry.OBSIDIAN, relative_path)
            header = self.__getFileHeader(lines)
            if header.get("project") != "open":
                continue

            # Preserve the existing rule: an open checkbox prevents automatic
            # generation even when its task metadata is invalid. Completed
            # checkboxes do not count as a next action.
            if any(self.__is_open_task_line(line) for line in lines):
                continue

            fallback_context = self.__getFallbackPolicy()
            task_text = "Define next action"
            normalized_path = relative_path.replace("\\", "/")

            def prepare(current_lines: list[str]) -> list[str]:
                updated = list(current_lines)
                current_header = self.__getFileHeader(updated)
                if current_header.get("project") != "open":
                    return updated
                if any(self.__is_open_task_line(line) for line in updated):
                    return updated

                line_number = len(updated)
                task_id = fallback_task_id(task_text, normalized_path, line_number)
                other_ids: set[str] = set()
                for other_file, _ in self.__fileBroker.getVaultFiles(VaultRegistry.OBSIDIAN):
                    if other_file.replace("\\", "/") == normalized_path or not other_file.lower().endswith(".md"):
                        continue
                    other_ids.update(self.__task_ids_from_lines(
                        self.__fileBroker.getVaultFileLines(VaultRegistry.OBSIDIAN, other_file),
                        other_file,
                    ))
                local_ids = self.__task_ids_from_lines(updated, relative_path)
                if task_id in other_ids or task_id in local_ids or task_id in known_task_ids:
                    raise AmbiguousTaskIdentityError("The prepared Markdown task identifier is already in use")

                task_line = f"- [ ] {task_text} [track::{fallback_context}] [id::{task_id}]\n"
                candidate = self.__getTaskDictFromLine(task_line, relative_path, line_number, current_header)
                if candidate["valid"] != "True":
                    return updated
                if updated and not updated[-1].endswith(("\n", "\r")):
                    updated[-1] += "\n"
                updated.append(task_line)
                return updated

            committed_lines = self.__fileBroker.updateVaultFileLines(
                VaultRegistry.OBSIDIAN,
                relative_path,
                prepare,
            )
            known_task_ids.update(self.__task_ids_from_lines(committed_lines, relative_path))

        # Always parse again so the returned view reflects the persisted
        # Markdown and receives the physical line number used by the model.
        return self.getJson()

    def __task_ids_from_lines(self, lines: list[str], relative_path: str) -> set[str]:
        identities: set[str] = set()
        normalized_path = relative_path.replace("\\", "/")
        for line_number, line in enumerate(lines):
            match = self._TASK_LINE.match(line)
            if match is None:
                continue
            body = match.group(2)
            metadata = list(self._TASK_METADATA.finditer(body))
            text = body[:metadata[0].start()].strip() if metadata else body.strip()
            declared_ids = [
                validate_task_id(item.group(2).strip())
                for item in metadata
                if item.group(1).strip() == "id"
            ]
            if len(set(declared_ids)) > 1:
                raise InvalidTaskIdentityError("A Markdown task declares conflicting identifiers")
            identities.add(declared_ids[0] if declared_ids else fallback_task_id(text, normalized_path, line_number))
        return identities

    @staticmethod
    def _task_id(task: dict[str, str]) -> str:
        if "id" in task:
            return validate_task_id(task["id"])
        return fallback_task_id(
            task["taskText"],
            task["file"].replace("\\", "/"),
            int(task["line"]),
        )

    def __process_task_file(
        self,
        file: tuple[str, float],
        task_list: TaskJsonListType,
        project_list: ProjectJsonListType,
    ) -> None:
        fileContent = self.__fileBroker.getVaultFileLines(VaultRegistry.OBSIDIAN, file[0])
        fileHeader = self.__getFileHeader(fileContent)
        taskLines = self.__getFileTaskLines(fileContent, fileHeader)

        if "project" in fileHeader and fileHeader["project"] in VALID_PROJECT_STATUS:
            fileName = file[0].replace("\\", "/").split("/")[-1].rsplit(".md", 1)[0]
            status = fileHeader["project"]
            project_list.append({
                "name": fileName,
                "status": status,
                "path": file[0]
            })

        for lineNum, line in taskLines:
            taskDict = self.__getTaskDictFromLine(line, file[0], lineNum, fileHeader)
            if taskDict["valid"] == "False":
                continue
            self.__update_or_append_task(taskDict, task_list)

    def __is_open_task_line(self, line: str) -> bool:
        match = self._TASK_LINE.match(line)
        return match is not None and match.group(1) == " "

    def __update_or_append_task(self, taskDict: dict[str, str], task_list: TaskJsonListType) -> None:
        found = False
        for i in range(len(task_list)):
            if task_list[i]["file"] == taskDict["file"] and task_list[i]["line"] == taskDict["line"]:
                task_list[i] = taskDict
                found = True
                break
        if not found:
            task_list.append(taskDict)

    def saveJson(self, json: TaskJsonType) -> None:
        # Markdown is edited through task/project operations, not bulk JSON.
        pass

    def __getFileHeader(self, file: list[str]) -> dict[str, str]:
        header: dict[str, str] = {}
        inHeader = False
        for line in file:
            if line.strip() == "---":
                if inHeader:
                    break
                inHeader = True
                continue

            if inHeader:
                key, separator, value = line.partition(":")
                if separator:
                    header[key.strip()] = value.strip()
        return header

    def __getFileTaskLines(self, file: list[str], fileHeader: dict[str, str]) -> list[tuple[int, str]]:
        return [
            (line_number, line)
            for line_number, line in enumerate(file)
            if self._TASK_LINE.match(line) is not None
        ]

    def __getDefaultTaskDict(self) -> dict[str, str]:
        return {
            "taskText": "",
            "starts": str(TimePoint.today()),
            "due": str(TimePoint.today()),
            "severity": "1",
            "remaining_cost": "1",
            "invested": "0",
            "status": " ",
            "file": "",
            "line": "0",
            "calm": "false"
        }

    def __getTaskDictFromLine(self, line: str, file: str, lineNum: int, fileHeader: dict[str, str]) -> dict[str, str]:
        taskDict = self.__getDefaultTaskDict()
        taskDict["file"] = file
        taskDict["line"] = str(lineNum)

        checkbox = self._TASK_LINE.match(line)
        if checkbox is None:
            taskDict["valid"] = "False"
            return taskDict

        taskDict["status"] = "x" if checkbox.group(1).lower() == "x" else " "
        textAfterCheckbox = checkbox.group(2)
        firstMetadata = self._TASK_METADATA.search(textAfterCheckbox)
        taskDict["taskText"] = textAfterCheckbox[:firstMetadata.start()].strip() if firstMetadata else textAfterCheckbox.strip()

        # Frontmatter supplies defaults; explicit task metadata then overrides it.
        for key, value in fileHeader.items():
            taskDict[key] = value
        # Task identity is defined by a tag on the task line, never by file-wide metadata.
        taskDict.pop("id", None)

        declared_ids: list[str] = []
        for match in self._TASK_METADATA.finditer(textAfterCheckbox):
            key = match.group(1).strip()
            value = match.group(2).strip()
            if key == "id":
                declared_ids.append(validate_task_id(value))
            else:
                taskDict[key] = value
        if declared_ids:
            if len(set(declared_ids)) > 1:
                raise InvalidTaskIdentityError("A Markdown task declares conflicting identifiers")
            taskDict["id"] = declared_ids[0]

        try:
            taskDict["starts"] = self.__apply_date_policy(taskDict["starts"])
            taskDict["due"] = self.__apply_date_policy(taskDict["due"])
            taskDict["track"] = self.__apply_track_policy(taskDict.get("track"))
            severity = float(taskDict["severity"])
            remaining_cost = float(taskDict["remaining_cost"])
            invested = float(taskDict["invested"])
            total_cost = remaining_cost - invested
            if not all(math.isfinite(value) for value in (severity, remaining_cost, invested, total_cost)):
                raise ValueError("Task numeric metadata must be finite")
            taskDict["severity"] = str(severity)
            taskDict["total_cost"] = str(total_cost)
            taskDict["effort_invested"] = taskDict["invested"]
            taskDict["valid"] = "True"
        except ValueError:
            print("Invalid task metadata was skipped; diagnostic details are suppressed.")
            taskDict["valid"] = "False"

        return taskDict

    def __apply_date_policy(self, date: str) -> str:
        try:
            return str(TimePoint.from_string(date).as_int())
        except ValueError:
            if self.__policies.date_missing_policy == "1":
                return str(TimePoint.today().as_int())
            raise ValueError(f"Invalid date format: {date}. Expected format is YYYY-MM-DD or YYYY-MM-DDTHH:MM")

    def __apply_track_policy(self, track: str | None) -> str:
        def is_prefix_of(prefix: str | None) -> bool:
            return any(isinstance(prefix, str) and prefix.startswith(context) for context in self.__policies.categories_prefixes)

        if not is_prefix_of(track):
            if self.__policies.context_missing_policy == "1":
                return self.__policies.default_context
            raise ValueError("Track tag is missing and no default value is set.")

        assert isinstance(track, str)
        return track

    def __getFallbackPolicy(self) -> str | None:
        if self.__policies.default_context in self.__policies.categories_prefixes:
            return self.__policies.default_context
        return self.__policies.categories_prefixes[0] if self.__policies.categories_prefixes else None
