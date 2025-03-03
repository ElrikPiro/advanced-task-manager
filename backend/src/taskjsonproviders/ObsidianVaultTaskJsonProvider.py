from ..wrappers.TimeManagement import TimePoint
from ..Interfaces.ITaskJsonProvider import ITaskJsonProvider
from ..Interfaces.IFileBroker import IFileBroker, VaultRegistry


class ObsidianVaultTaskJsonProvider(ITaskJsonProvider):

    def __init__(self, fileBroker: IFileBroker):
        self.__fileBroker = fileBroker
        self._lastJson = {"tasks": [], "pomodoros_per_day": "2"}
        self._lastJsonList: list = []
        self._lastMtime = 0.0

    def getJson(self) -> dict:
        vaultFiles = self.__fileBroker.getVaultFiles(VaultRegistry.OBSIDIAN)
        if len(vaultFiles) == 0:
            return {}

        # filter in all .md files in the vault
        vaultFiles = [file for file in vaultFiles if file[0].endswith(".md")]

        mtime = max([file[1] for file in vaultFiles], default=0)
        if mtime <= self._lastMtime:
            return self._lastJson

        # get a list for all files that have been modified since the last check
        modifiedFiles = vaultFiles

        # delete all tasks from the last json that are in the modified files
        self._lastJsonList = []

        # add all tasks from the modified files to the last json
        for file in modifiedFiles:
            try:
                fileContent = self.__fileBroker.getVaultFileLines(VaultRegistry.OBSIDIAN, file[0])
                fileHeader = self.__getFileHeader(fileContent)
                taskLines = self.__getFileTaskLines(fileContent, fileHeader)
                for lineNum, line in taskLines:
                    taskDict = self.__getTaskDictFromLine(line, file[0], lineNum, fileHeader)
                    if taskDict["valid"] == "False":
                        continue
                    # check if there is a task with the same file and line in the last json
                    # if so, update the task, otherwise append it
                    found = False
                    for i in range(len(self._lastJsonList)):
                        if self._lastJsonList[i]["file"] == taskDict["file"] and self._lastJsonList[i]["line"] == taskDict["line"]:
                            self._lastJsonList[i] = taskDict
                            found = True
                            break
                    if not found:
                        self._lastJsonList.append(taskDict)
            except Exception as e:
                print(f"Error while reading file {file[0]}: {e}")
        self._lastMtime = mtime
        self._lastJson["tasks"] = self._lastJsonList
        return self._lastJson

    def saveJson(self, json: dict):
        # do nothing
        pass

    def __getFileHeader(self, file: list[str]) -> dict:
        header = {}
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
    
    def __getFileTaskLines(self, file: list[str], fileHeader: dict) -> list[(int, str)]:
        taskLines = []
        for i in range(len(file)):
            if file[i].strip().startswith("- [ ]"):
                taskLines.append((i, file[i]))
        return taskLines
        
    def __getDefaultTaskDict(self) -> dict:
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

    def __getTaskDictFromLine(self, line: str, file: str, lineNum: int, fileHeader: dict) -> dict:
        taskDict = self.__getDefaultTaskDict()
        taskDict["file"] = file
        taskDict["line"] = str(lineNum)

        # if file == "\\".join("SecondBrain/PARA/2. Areas/Legal/202304290908-DNI Renovacion.md".split("/")):
        #     print("here")

        # get task text
        # task text is everything after "- [ ]" and before any [] containing a "::"
        textAfterCheckbox = line.split("- [ ]")[1]
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
            taskDict["starts"] = str(TimePoint.from_string(taskDict["starts"]).as_int())
            taskDict["due"] = str(TimePoint.from_string(taskDict["due"]).as_int())
            taskDict["valid"] = "True" if taskDict.get("track") is not None else "False"
            taskDict["total_cost"] = str(float(taskDict["remaining_cost"]) - float(taskDict["invested"]))
            taskDict["effort_invested"] = taskDict["invested"]
        except Exception:
            taskDict["valid"] = "False"
            pass

        return taskDict


