import json
from .Interfaces.IProjectManager import IProjectManager, ProjectCommands
from .Interfaces.ITaskJsonProvider import VALID_PROJECT_STATUS, ITaskJsonProvider
from .Utils import stripDoc

from typing import List


class JsonProjectManager(IProjectManager):
    """
    Implementation of the project manager interface.
    Handles project management operations and processes commands.
    """

    def __init__(self, taskListProvider: ITaskJsonProvider):
        """
        Initialize the ProjectManager with an empty projects dictionary.
        """
        self.__taskListProvider = taskListProvider
        self.commands: dict[str, callable] = {
            ProjectCommands.LIST.value: self._list_projects,
            ProjectCommands.CAT.value: self._cat_project,
            ProjectCommands.EDIT.value: self._edit_project_description,
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
        if command in self.commands.keys():
            return self.commands.get(command, self._get_help)(messageArgs)
        else:
            return self._get_help()

    def _get_help(self, messageArgs: List[str] = []) -> str:
        """
        # Projects Command Manual
        This manual provides a list of commands that can be used to manage projects.
        Project management is done through the Json file. Projects are stored in the json as anonymous objects.
        The project status can be 'open', 'closed', or 'hold'.

        Following the Get Things Done (GTD) methodology, projects are defined as outcomes that require more than one task to complete.
        Each project file should have a title, a description, and at least one task, defined as "next action".
        **In case no tasks are defined in an open project, the json provider will automatically define a virtual task to remind the user to define the next action.**

        send /projects help <command> to get more information about a specific command.

        ## Commands
        - list [status] - List all projects with the specified status.
        - cat <project_name> - Get the contents of a project.
        - edit <project_name> <line_number> <new_content> - Edit a line in a project.
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
            projectList = self.__taskListProvider.getJson().get("projects", [])
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
        Get the description of a project.

        Projects are stored in the json as anonymous objects and this command will show them as they are stored.
        """
        if len(messageArgs) == 0:
            return "No project name provided"

        projName = messageArgs[0].replace("_", " ")
        projectList = self.__taskListProvider.getJson().get("projects", [])
        projectList = [project for project in projectList if project["name"] == projName]

        if len(projectList) == 0:
            return f"Project {messageArgs[0]} not found"

        projectJson = json.dumps(projectList[0], indent=4)

        return projectJson

    def _edit_project_description(self, messageArgs: List[str]) -> str:
        """
        # Command: edit <project_name> <new_content>
        Edits the project description.

        The command will replace the content of the description with the new content provided.
        """
        if len(messageArgs) < 2:
            return "Format: edit project_name new_content"

        projName = messageArgs[0].replace("_", " ")
        taskJson = self.__taskListProvider.getJson()
        projectList = taskJson.get("projects", [])
        projectListFiltered = [project for project in projectList if project["name"] == projName]

        if len(projectListFiltered) == 0:
            return f"Project {messageArgs[0]} not found"

        project = projectListFiltered[0]
        project["description"] = " ".join(messageArgs[1:])

        self.__taskListProvider.saveJson(taskJson)
        return f"Description updated for {messageArgs[0]} successfully"

    def _update_project_status(self, project_name: str, new_status: str) -> str:
        """
        Helper function to update project status in frontmatter

        Args:
            project_name (str): Name of the project
            new_status (str): New status to set ('open', 'closed', or 'hold')

        Returns:
            str: Result message
        """
        taskJson = self.__taskListProvider.getJson()
        projectList = taskJson.get("projects", [])
        projectListFiltered = [project for project in projectList if project["name"] == project_name]

        if len(projectListFiltered) == 0:
            return f"Project {project_name} not found"

        project = projectListFiltered[0]
        project["status"] = new_status

        self.__taskListProvider.saveJson(taskJson)
        return f"Project {project_name} status updated to {new_status}"

    def _open_project(self, messageArgs: List[str]) -> str:
        """
        # Command: open <project_name> (<description>)
        Open a project or create a new one.

        If the project doesn't exist, a new project will be created.
        """
        if len(messageArgs) < 1:
            return "Format: open project_name (optional_description)"

        project_name = messageArgs[0].replace("_", " ")
        project_description = " ".join(messageArgs[1:] if len(messageArgs) > 1 else [])
        projectList = self.__taskListProvider.getJson().get("projects", [])
        projectListFiltered = [project for project in projectList if project["name"] == project_name]

        if len(projectListFiltered) == 0:
            # Project doesn't exist, create a new one
            projectList.append({
                "name": project_name,
                "description": project_description,
                "status": "open"
            })

            taskJson = self.__taskListProvider.getJson()
            taskJson["projects"] = projectList
            self.__taskListProvider.saveJson(taskJson)
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
