from src.Utils import ProjectJsonListType, TaskDiscoveryPolicies, TaskJsonListType, TaskJsonType
from ..wrappers.TimeManagement import TimePoint
from ..Interfaces.ITaskJsonProvider import ITaskJsonProvider, VALID_PROJECT_STATUS
from ..Interfaces.IFileBroker import IFileBroker, VaultRegistry


class ObsidianVaultTaskJsonProvider(ITaskJsonProvider):

    def __init__(self, fileBroker: IFileBroker, policies: TaskDiscoveryPolicies):
        self.__fileBroker = fileBroker
        self._lastJson: TaskJsonType = {"tasks": []}
        self._lastJsonList: TaskJsonListType = []
        self.__lastProjectList: ProjectJsonListType = []
        self._lastMtime = 0.0
        self.__policies = policies

    def getJson(self) -> TaskJsonType:
        vaultFiles = self.__fileBroker.getVaultFiles(VaultRegistry.OBSIDIAN)
        if len(vaultFiles) == 0:
            return {}

        # filter in all .md files in the vault
        vaultFiles = [file for file in vaultFiles if file[0].endswith(".md")]

        mtime = max([file[1] for file in vaultFiles], default=0)
        if mtime <= self._lastMtime:
            return self._lastJson

        self._lastJson = {"tasks": []}
        self._lastJsonList = []
        self.__lastProjectList = []

        # add all tasks from the modified files to the last json
        for file in vaultFiles:
            try:
                self.__process_task_file(file)
            except Exception as e:
                print(f"Error while reading file {file[0]}: {e}")
        self._lastMtime = mtime
        self._lastJson["tasks"] = self._lastJsonList
        self._lastJson["projects"] = self.__lastProjectList
        return self._lastJson

    def __process_task_file(self, file: tuple[str, float]) -> None:
        fileContent = self.__fileBroker.getVaultFileLines(VaultRegistry.OBSIDIAN, file[0])
        fileHeader = self.__getFileHeader(fileContent)
        taskLines = self.__getFileTaskLines(fileContent, fileHeader)

        if "project" in fileHeader and fileHeader["project"] in VALID_PROJECT_STATUS:
            fileName = file[0].replace("\\", "/").split("/")[-1].split(".md")[0]
            status = fileHeader["project"]
            element = {
                "name": fileName,
                "status": status,
                "path": file[0]
            }
            self.__lastProjectList.append(element)

            if len(taskLines) == 0 and status == "open":
                taskDict = self.__getTaskDictFromLine(
                    f"- [ ] Define next action [track::{self.__getFallbackPolicy()}]",
                    file[0], len(fileContent),
                    fileHeader
                )
                self.__update_or_append_task(taskDict)

        for lineNum, line in taskLines:
            taskDict = self.__getTaskDictFromLine(line, file[0], lineNum, fileHeader)
            if taskDict["valid"] == "False":
                continue
            self.__update_or_append_task(taskDict)

    def __update_or_append_task(self, taskDict: dict[str, str]) -> None:
        found = False
        for i in range(len(self._lastJsonList)):
            if self._lastJsonList[i]["file"] == taskDict["file"] and self._lastJsonList[i]["line"] == taskDict["line"]:
                self._lastJsonList[i] = taskDict
                found = True
                break
        if not found:
            self._lastJsonList.append(taskDict)

    def saveJson(self, json: TaskJsonType) -> None:
        # do nothing
        pass

    def __getFileHeader(self, file: list[str]) -> dict[str, str]:
        header: dict[str, str] = {}
        inHeader = False
        for line in file:
            if line.split('\n')[0].strip() == "---":
                if inHeader:
                    break
                else:
                    inHeader = True
                    continue

            if inHeader:
                splittedLine = line.split(":")
                key = splittedLine[0].strip()
                value = splittedLine[-1].strip()
                header[key] = value
        return header

    def __getFileTaskLines(self, file: list[str], fileHeader: dict[str, str]) -> list[tuple[int, str]]:
        taskLines: list[tuple[int, str]] = []
        for i in range(len(file)):
            if file[i].strip().startswith("- [ ]"):
                taskLines.append((i, file[i]))
        return taskLines

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
        # track is ommited so that the task is invalid by default

    def __getTaskDictFromLine(self, line: str, file: str, lineNum: int, fileHeader: dict[str, str]) -> dict[str, str]:
        taskDict = self.__getDefaultTaskDict()
        taskDict["file"] = file
        taskDict["line"] = str(lineNum)

        # if file == "\\".join("SecondBrain/PARA/2. Areas/Legal/202304290908-DNI Renovacion.md".split("/")):
        #     print("here")

        # get task text
        # task text is everything after "- [ ]" and before any [] containing a "::"
        lineMod = line + "[eol:: here]"
        textAfterCheckbox = lineMod.split("- [ ]")[1]
        textBeforeFirstDualColon = textAfterCheckbox.split("::")[0]
        splittedByCorchetes = textBeforeFirstDualColon.split("[")
        allButLast = splittedByCorchetes[:-1]
        taskDict["taskText"] = "[".join(allButLast).strip()

        # override default values with values from the file header
        for key in fileHeader:
            taskDict[key] = fileHeader[key]

        lineData = line.split("- [ ]")[1].split("[")
        # keyvalue are in the format "[key:: value]"
        for keyValueRegion in lineData[1:]:
            try:
                keyValue = keyValueRegion.split("::")
                key = keyValue[0].strip()
                value = keyValue[1].split("]")[0].strip()
                taskDict[key] = value
            except Exception:
                pass

        # special case for starts and due that should be converted to int
        try:
            taskDict["starts"] = self.__apply_date_policy(taskDict["starts"])
            taskDict["due"] = self.__apply_date_policy(taskDict["due"])
            taskDict["track"] = self.__apply_track_policy(taskDict.get("track", None))
            taskDict["severity"] = str(float(taskDict["severity"]))
            taskDict["total_cost"] = str(float(taskDict["remaining_cost"]) - float(taskDict["invested"]))
            taskDict["effort_invested"] = taskDict["invested"]
            taskDict["valid"] = "True"
        except Exception as ex:
            print(f"Error while processing task {taskDict['taskText']} in file {file} at line {lineNum}: {ex}")
            taskDict["valid"] = "False"
            pass

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
            isPrefix = False
            for context in self.__policies.categories_prefixes:
                if isinstance(prefix, str) and prefix.startswith(context):
                    isPrefix = True
                    break
            return isPrefix

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
