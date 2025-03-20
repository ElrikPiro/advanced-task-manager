from typing import List

from .Utils import stripDoc
from .Interfaces.IProjectManager import IProjectManager, ProjectCommands
from .Interfaces.ITaskJsonProvider import VALID_PROJECT_STATUS
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
            ProjectCommands.HOLD.value: self._hold_project,
            ProjectCommands.HELP.value: self._get_help
        }

    def process_command(self, command: str, messageArgs: List[str]) -> str:
        """
        Process a command with its arguments.

        Args:
            command (str): The command to process.
            messageArgs (List[str]): Arguments for the command.
        Returns:
            str: The result of the command
        """
        if command in ProjectCommands.values():
            return self.commands.get(command, self._get_help)(messageArgs)
        else:
            return self._get_help()

    def _get_help(self, messageArgs: List[str] = []) -> str:
        """
        # Projects Command Manual
        This manual provides a list of commands that can be used to manage projects.
        Project management is done through the Markdown vault. Projects are stored in the vault as markdown files.
        These files must have a frontmatter with a 'project' attribute that specifies the project status.
        The project status can be 'open', 'closed', or 'hold'.

        Following the Get Things Done (GTD) methodology, projects are defined as outcomes that require more than one task to complete.
        Each project file should have a title, a description, and at least one task, defined as "next action".
        **In case no tasks are defined in an open project, the Markdown json provider will automatically define a virtual task to remind the user to define the next action.**

        send /projects help <command> to get more information about a specific command.

        ## Commands
        - list [status] - List all projects with the specified status.
        - cat <project_name> - Get the contents of a project.
        - edit <project_name> <line_number> <new_content> - Edit a line in a project.
        - add <project_name> <line_number> <new_content> - Add a new line to a project.
        - remove <project_name> <line_number> - Remove a line from a project.
        - open <project_name> - Open a project or create a new one.
        - close <project_name> - Close a project.
        - hold <project_name> - Put a project on hold.
        """
        if len(messageArgs) > 0:
            command = messageArgs[0]
            if command in ProjectCommands.values():
                return stripDoc(self.commands[command].__doc__)
            else:
                return f"Command {command} not found"
        return stripDoc(self._get_help.__doc__)

    def _list_projects(self, messageArgs: List[str]) -> str:
        """
        # Command: list [status]
        List all projects with the specified status.
        If no status is provided, lists all open projects.

        Valid statuses are: `open`, `closed` and `on-hold`.
        """
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
        # Command: cat <project_name>
        Get the contents of a project.

        Projects are stored in the vault as markdown files and this command will show them as they are stored. Line numbers are prepended to each line for reference.
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
        # Command: edit <project_name> <line_number> <new_content>
        Edit a line in a project.

        The command will replace the content of the line with the new content provided.
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
        # Command: add <project_name> <line_number> <new_content>
        Add a new line to a project.

        The command will insert the new content at the specified line number.
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
        # Command: remove <project_name> <line_number>
        Remove a line from a project.

        The command will remove the line at the specified line number.
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
        # Command: open <project_name>
        Open a project or create a new one.

        If the project doesn't exist, a new project will be created.
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
        # Command: close <project_name>
        Close a project.

        The project status will be set to 'closed'.
        """
        if len(messageArgs) == 0:
            return "Format: close project_name"

        return self._update_project_status(messageArgs[0], "closed")

    def _hold_project(self, messageArgs: List[str]) -> str:
        """
        # Command: hold <project_name>
        Put a project on hold.

        The project status will be set to 'hold'.
        """
        if len(messageArgs) == 0:
            return "Format: hold project_name"

        return self._update_project_status(messageArgs[0], "hold")
