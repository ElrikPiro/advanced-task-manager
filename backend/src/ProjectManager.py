from typing import List
from .Interfaces.IProjectManager import IProjectManager, ProjectCommands
from .Interfaces.ITaskJsonProvider import VALID_PROJECT_STATUS, ITaskJsonProvider
from .Interfaces.ITaskProvider import ITaskProvider
from .Interfaces.IFileBroker import IFileBroker, VaultRegistry


class ObsidianProjectManager(IProjectManager):
    """
    Implementation of the project manager interface.
    Handles project management operations and processes commands.
    """

    def __init__(self, taskListProvider: ITaskProvider, fileBroker: IFileBroker):
        """
        Initialize the ProjectManager with an empty projects dictionary.
        """
        self.__taskListProvider = taskListProvider
        self.__fileBroker = fileBroker
        self.commands: dict[str, callable] = {
            ProjectCommands.LIST.value: self._list_projects,
            ProjectCommands.CAT.value: self._cat_project,
            ProjectCommands.EDIT.value: self._edit_project_line,
            ProjectCommands.ADD.value: self._add_project_line,
            ProjectCommands.REMOVE.value: self._remove_project_line,
            ProjectCommands.OPEN.value: self._open_project,
            ProjectCommands.CLOSE.value: self._close_project,
            ProjectCommands.HOLD.value: self._hold_project
        }

    def process_command(self, command: str, messageArgs: List[str]) -> str:
        """
        Process a command with its arguments.

        Args:
            command (str): The command to process.
            messageArgs (List[str]): Arguments for the command.
        """
        if command in ProjectCommands.values():
            return self.commands[command](messageArgs)
        else:
            return self._get_help()

    def _get_help(self) -> str:
        """
        Get the help message for the project manager.

        Returns:
            str: The help message.
        """
        return "Available commands: " + ", ".join(ProjectCommands.values())

    def _list_projects(self, messageArgs: List[str]) -> str:
        retval: list[str] = []
        if len(messageArgs) == 0:
            messageArgs.append("open")

        if messageArgs[0] in VALID_PROJECT_STATUS:
            retval.append(f"Projects with status {messageArgs[0]}:")
            projectList = self.__taskListProvider.getTaskListAttribute("projects")
            projectList = [project for project in projectList if project["status"] == messageArgs[0]]
        else:
            return f"Invalid project status {messageArgs[0]}"
        pass

        # list the projects with a enumerated list in which the number has 2 digits
        for i, project in enumerate(projectList):
            retval.append(f"{(i+1):02d}: {project['name'].strip().replace(' ', '_')}")

        return "\n".join(retval)

    def _cat_project(self, messageArgs: List[str]) -> str:
        """
        gets the content of a project file
        """
        if len(messageArgs) == 0:
            return "No project name provided"

        fileName = messageArgs[0].replace("_", " ")
        projectList = self.__taskListProvider.getTaskListAttribute("projects")
        projectList = [project for project in projectList if project["name"] == fileName]

        if len(projectList) == 0:
            return f"Project {messageArgs[0]} not found"

        projectPath = projectList[0]["path"]

        lines = self.__fileBroker.getVaultFileLines(VaultRegistry.OBSIDIAN, projectPath)
        # foreach line set the line number with a 3 digit number
        for i, line in enumerate(lines):
            lines[i] = f"{(i+1):03d}: {line}"
        return "".join(lines)

    def _edit_project_line(self, messageArgs: List[str]) -> str:
        """
        Edits a line in a project file.
        Format: edit project_name line_number new_content
        """
        if len(messageArgs) < 3:
            return "Format: edit project_name line_number new_content"

        fileName = messageArgs[0].replace("_", " ")
        projectList = self.__taskListProvider.getTaskListAttribute("projects")
        projectList = [project for project in projectList if project["name"] == fileName]

        if len(projectList) == 0:
            return f"Project {messageArgs[0]} not found"

        try:
            lineNumber = int(messageArgs[1])
        except ValueError:
            return f"Invalid line number: {messageArgs[1]}"

        projectPath = projectList[0]["path"]
        lines = self.__fileBroker.getVaultFileLines(VaultRegistry.OBSIDIAN, projectPath)

        if lineNumber < 1 or lineNumber > len(lines):
            return f"Line number {lineNumber} out of range. File has {len(lines)} lines."

        # Join the remaining arguments as the new line content
        newContent = " ".join(messageArgs[2:])
        lines[lineNumber - 1] = newContent + "\n"

        self.__fileBroker.writeVaultFileLines(VaultRegistry.OBSIDIAN, projectPath, lines)
        return f"Line {lineNumber} in {messageArgs[0]} updated successfully"

    def _add_project_line(self, messageArgs: List[str]) -> str:
        """
        Adds a new line in a project file at the specified position.
        Format: add project_name line_number new_content
        """
        if len(messageArgs) < 3:
            return "Format: add project_name line_number new_content"

        fileName = messageArgs[0].replace("_", " ")
        projectList = self.__taskListProvider.getTaskListAttribute("projects")
        projectList = [project for project in projectList if project["name"] == fileName]

        if len(projectList) == 0:
            return f"Project {messageArgs[0]} not found"

        try:
            lineNumber = int(messageArgs[1])
        except ValueError:
            return f"Invalid line number: {messageArgs[1]}"

        projectPath = projectList[0]["path"]
        lines = self.__fileBroker.getVaultFileLines(VaultRegistry.OBSIDIAN, projectPath)

        if lineNumber < 1 or lineNumber > len(lines) + 1:
            return f"Line number {lineNumber} out of range. File has {len(lines)} lines."

        # Join the remaining arguments as the new line content
        newContent = " ".join(messageArgs[2:])
        lines.insert(lineNumber - 1, newContent + "\n")

        self.__fileBroker.writeVaultFileLines(VaultRegistry.OBSIDIAN, projectPath, lines)
        return f"Line added at position {lineNumber} in {messageArgs[0]} successfully"

    def _remove_project_line(self, messageArgs: List[str]) -> str:
        """
        Removes a line from a project file.
        Format: remove project_name line_number
        """
        if len(messageArgs) < 2:
            return "Format: remove project_name line_number"

        fileName = messageArgs[0].replace("_", " ")
        projectList = self.__taskListProvider.getTaskListAttribute("projects")
        projectList = [project for project in projectList if project["name"] == fileName]

        if len(projectList) == 0:
            return f"Project {messageArgs[0]} not found"

        try:
            lineNumber = int(messageArgs[1])
        except ValueError:
            return f"Invalid line number: {messageArgs[1]}"

        projectPath = projectList[0]["path"]
        lines = self.__fileBroker.getVaultFileLines(VaultRegistry.OBSIDIAN, projectPath)

        if lineNumber < 1 or lineNumber > len(lines):
            return f"Line number {lineNumber} out of range. File has {len(lines)} lines."

        lines.pop(lineNumber - 1)

        self.__fileBroker.writeVaultFileLines(VaultRegistry.OBSIDIAN, projectPath, lines)
        return f"Line {lineNumber} removed from {messageArgs[0]} successfully"

    def _update_project_status(self, project_name: str, new_status: str) -> str:
        """
        Helper function to update project status in frontmatter

        Args:
            project_name (str): Name of the project
            new_status (str): New status to set ('open', 'closed', or 'hold')

        Returns:
            str: Result message
        """
        project_name = project_name.replace("_", " ")
        projectList = self.__taskListProvider.getTaskListAttribute("projects")
        existing_project = [project for project in projectList if project["name"] == project_name]

        if len(existing_project) == 0:
            return f"Project {project_name} does not exist"

        # Project exists, update its status
        project = existing_project[0]
        project_path = project["path"]

        lines = self.__fileBroker.getVaultFileLines(VaultRegistry.OBSIDIAN, project_path)

        # Find the project status line in the frontmatter and update it
        frontmatter_found = False
        status_updated = False
        for i, line in enumerate(lines):
            if line.strip() == "---":
                if not frontmatter_found:
                    frontmatter_found = True
                else:
                    # We've reached the end of frontmatter without finding the project status
                    # Insert the status line before the closing ---
                    lines.insert(i, f"project: {new_status}\n")
                    status_updated = True
                    break
            elif "project:" in line and frontmatter_found:
                lines[i] = f"project: {new_status}\n"
                status_updated = True
                break

        if not status_updated and frontmatter_found:
            # Find the second --- and insert before it
            for i, line in enumerate(lines):
                if line.strip() == "---" and i > 0:
                    lines.insert(i, f"project: {new_status}\n")
                    break

        self.__fileBroker.writeVaultFileLines(VaultRegistry.OBSIDIAN, project_path, lines)
        return f"Project {project_name} is now {new_status}"

    def _open_project(self, messageArgs: List[str]) -> str:
        """
        Opens a project by setting its status to 'open'.
        If the project doesn't exist, it creates a new project file.
        Format: open project_name
        """
        if len(messageArgs) == 0:
            return "Format: open project_name"

        project_name = messageArgs[0].replace("_", " ")
        projectList = self.__taskListProvider.getTaskListAttribute("projects")
        existing_project = [project for project in projectList if project["name"] == project_name]

        if len(existing_project) == 0:
            # Project doesn't exist, create a new one
            project_path = f"{project_name}.md"
            content = [
                "---\n",
                "project: open\n",
                "---\n",
                f"# {project_name}\n",
                "\n",
                "## Description\n",
                "\n",
                "## Tasks\n",
                "\n"
            ]
            self.__fileBroker.writeVaultFileLines(VaultRegistry.OBSIDIAN, project_path, content)

            return f"Created new project: {project_name}"
        else:
            # Project exists, use the helper function to update its status to 'open'
            return self._update_project_status(messageArgs[0], "open")

    def _close_project(self, messageArgs: List[str]) -> str:
        """
        Closes a project by setting its status to 'closed'.
        Format: close project_name
        """
        if len(messageArgs) == 0:
            return "Format: close project_name"

        return self._update_project_status(messageArgs[0], "closed")

    def _hold_project(self, messageArgs: List[str]) -> str:
        """
        Puts a project on hold by setting its status to 'hold'.
        Format: hold project_name
        """
        if len(messageArgs) == 0:
            return "Format: hold project_name"

        return self._update_project_status(messageArgs[0], "hold")


class JsonProjectManager(IProjectManager):
    """
    Implementation of the project manager interface that manages projects inside a single json file.
    """

    def __init__(self, taskListProvider: ITaskJsonProvider):
        """
        Initialize the JsonProjectManager with the necessary providers.
        """
        self.__taskListProvider = taskListProvider
        self.commands: dict[str, callable] = {
            ProjectCommands.LIST.value: self._list_projects,
            ProjectCommands.CAT.value: self._cat_project,
            ProjectCommands.EDIT.value: self._edit_project_line,
            ProjectCommands.ADD.value: self._add_project_line,
            ProjectCommands.REMOVE.value: self._remove_project_line,
            ProjectCommands.OPEN.value: self._open_project,
            ProjectCommands.CLOSE.value: self._close_project,
            ProjectCommands.HOLD.value: self._hold_project
        }

    def process_command(self, command: str, messageArgs: List[str]) -> str:
        """
        Process a command with its arguments.

        Args:
            command (str): The command to process.
            messageArgs (List[str]): Arguments for the command.
        """
        return self._get_help()  # not yet implemented
        if command in ProjectCommands.values():
            return self.commands[command](messageArgs)
        else:
            return self._get_help()

    def _get_help(self) -> str:
        """
        Get the help message for the project manager.

        Returns:
            str: The help message.
        """
        return "Project manager is still not supported on standalone json files."

    def _list_projects(self, messageArgs: List[str]) -> str:
        """
        List projects with specified status.
        """

        return ""

    def _cat_project(self, messageArgs: List[str]) -> str:
        """
        Get the contents of a project.
        """
        return ""

    def _edit_project_line(self, messageArgs: List[str]) -> str:
        """
        Edit a line in a project.
        """
        return ""

    def _add_project_line(self, messageArgs: List[str]) -> str:
        """
        Add a new line to a project.
        """
        return ""

    def _remove_project_line(self, messageArgs: List[str]) -> str:
        """
        Remove a line from a project.
        """
        return ""

    def _update_project_status(self, project_name: str, new_status: str) -> str:
        """
        Helper function to update project status.
        """
        return ""

    def _open_project(self, messageArgs: List[str]) -> str:
        """
        Open a project or create a new one.
        """
        return ""

    def _close_project(self, messageArgs: List[str]) -> str:
        """
        Close a project.
        """
        return ""

    def _hold_project(self, messageArgs: List[str]) -> str:
        """
        Put a project on hold.
        """
        return ""
