import re

from src.Utils import ProjectJsonListType, TaskDiscoveryPolicies, TaskJsonListType, TaskJsonType
from ..wrappers.TimeManagement import TimePoint
from ..Interfaces.ITaskJsonProvider import ITaskJsonProvider, VALID_PROJECT_STATUS
from ..Interfaces.IFileBroker import IFileBroker, VaultRegistry


class ObsidianVaultTaskJsonProvider(ITaskJsonProvider):

    _TASK_LINE = re.compile(r"^\s*-\s+\[([ xX])\]\s*(.*)$")
    _TASK_METADATA = re.compile(r"\[([^\]:]+)::\s*([^\]]*)\]")

    def __init__(self, fileBroker: IFileBroker, policies: TaskDiscoveryPolicies):
        self.__fileBroker = fileBroker
        self.__policies = policies

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

    def discover(self) -> TaskJsonType:
        """Persist a default next action in each uncovered open project."""
        vaultFiles = [
            file for file in self.__fileBroker.getVaultFiles(VaultRegistry.OBSIDIAN)
            if file[0].lower().endswith(".md")
        ]
        for file in vaultFiles:
            relative_path = file[0]
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
            task_line = f"- [ ] Define next action [track::{fallback_context}]\n"
            candidate = self.__getTaskDictFromLine(task_line, relative_path, len(lines), header)
            if candidate["valid"] != "True":
                continue

            if lines and not lines[-1].endswith(("\n", "\r")):
                lines[-1] += "\n"
            lines.append(task_line)
            self.__fileBroker.writeVaultFileLines(VaultRegistry.OBSIDIAN, relative_path, lines)

        # Always parse again so the returned view reflects the persisted
        # Markdown and receives the physical line number used by the model.
        return self.getJson()

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

        for match in self._TASK_METADATA.finditer(textAfterCheckbox):
            taskDict[match.group(1).strip()] = match.group(2).strip()

        try:
            taskDict["starts"] = self.__apply_date_policy(taskDict["starts"])
            taskDict["due"] = self.__apply_date_policy(taskDict["due"])
            taskDict["track"] = self.__apply_track_policy(taskDict.get("track"))
            taskDict["severity"] = str(float(taskDict["severity"]))
            taskDict["total_cost"] = str(float(taskDict["remaining_cost"]) - float(taskDict["invested"]))
            taskDict["effort_invested"] = taskDict["invested"]
            taskDict["valid"] = "True"
        except ValueError as error:
            print(f"Error while processing task {taskDict['taskText']} in file {file} at line {lineNum}: {error}")
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
