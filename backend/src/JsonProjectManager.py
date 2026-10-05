import json
from copy import deepcopy
from .Interfaces.IProjectManager import IProjectManager, ProjectCommands
from .Interfaces.ITaskJsonProvider import VALID_PROJECT_STATUS, ITaskJsonProvider
from .MutationCoordinator import MutationCoordinator
from .Utils import stripDoc

from typing import Any, List, Callable, Mapping, cast
from uuid import uuid4
from src.Utils import TaskJsonType
from src.domain.errors import (
    AmbiguousResourceError,
    InvalidResourceDataError,
    OperationFailedError,
    ResourceNotFoundError,
    ValidationError,
)
from src.domain.models import ProjectMutationResult


class JsonProjectManager(IProjectManager):
    """
    Implementation of the project manager interface.
    Handles project management operations and processes commands.
    """

    _MUTATING_COMMANDS = frozenset({
        ProjectCommands.EDIT.value,
        ProjectCommands.OPEN.value,
        ProjectCommands.CLOSE.value,
        ProjectCommands.HOLD.value,
    })

    def __init__(
        self,
        taskListProvider: ITaskJsonProvider,
        mutation_coordinator: Any | None = None,
    ):
        """
        Initialize the ProjectManager with an empty projects dictionary.
        """
        self.__taskListProvider = taskListProvider
        broker = getattr(taskListProvider, "fileBroker", None)
        candidates = [
            getattr(source, "mutation_coordinator", None)
            for source in (taskListProvider, broker)
            if source is not None
        ]
        candidates = [candidate for candidate in candidates if isinstance(candidate, MutationCoordinator)]
        if len({id(candidate) for candidate in candidates}) > 1:
            raise ValueError("Project storage components must share one mutation coordinator")
        shared = mutation_coordinator if mutation_coordinator is not None else (
            candidates[0] if candidates else None
        )
        if mutation_coordinator is not None and any(
            candidate is not mutation_coordinator for candidate in candidates
        ):
            raise ValueError("Project storage components must share one mutation coordinator")
        self.mutation_coordinator = shared
        self.commands: dict[str, Callable[[List[str]], str]] = {
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
        if command not in self.commands:
            return self._get_help()
        arguments = list(messageArgs)
        handler = self.commands[command]
        if command in self._MUTATING_COMMANDS and self.mutation_coordinator is not None:
            intent = ("project-command", command, tuple(arguments))
            return cast(
                str,
                self.mutation_coordinator.run_operation(
                    uuid4(),
                    intent,
                    lambda admitted: handler(list(admitted[2])),
                ),
            )
        return handler(arguments)

    def perform_operation(
        self,
        operation_type: str,
        project_name: str,
        parameters: Mapping[str, Any],
    ) -> ProjectMutationResult:
        """Apply a typed project operation and return the saved project data."""
        self.validate_operation_structure(operation_type, project_name, parameters)
        coordinator = self.mutation_coordinator
        if coordinator is None:
            return self._perform_operation(operation_type, project_name, parameters)
        return cast(
            ProjectMutationResult,
            coordinator.run_or_inline(
                lambda: self._perform_operation(operation_type, project_name, parameters)
            ),
        )

    def _perform_operation(
        self,
        operation_type: str,
        project_name: str,
        parameters: Mapping[str, Any],
    ) -> ProjectMutationResult:
        results: list[ProjectMutationResult] = []
        if operation_type == "open-project":
            description = parameters.get("description", "")

            def open_project(current: TaskJsonType) -> TaskJsonType:
                results.clear()
                document = deepcopy(current)
                projects = self._typed_projects(document)
                matches = [project for project in projects if project.get("name") == project_name]
                if len(matches) > 1:
                    raise AmbiguousResourceError("More than one project has this name")
                created = False
                if matches:
                    project = self._find_typed_project(projects, project_name)
                    self._project_result(document, project_name)
                    project["status"] = "open"
                else:
                    projects.append({
                        "name": project_name,
                        "description": description,
                        "status": "open",
                    })
                    cast(dict[str, Any], document)["projects"] = projects
                    created = True
                results.append(self._project_result(document, project_name, created=created))
                return document

            self.__taskListProvider.updateJson(open_project)
        elif operation_type in {"close-project", "hold-project"}:
            status = "closed" if operation_type == "close-project" else "on-hold"

            def update_status(current: TaskJsonType) -> TaskJsonType:
                results.clear()
                document = deepcopy(current)
                project = self._find_typed_project(self._typed_projects(document), project_name)
                self._project_result(document, project_name)
                project["status"] = status
                results.append(self._project_result(document, project_name))
                return document

            self.__taskListProvider.updateJson(update_status)
        elif operation_type == "edit-project-content":
            description = parameters.get("description")
            if not isinstance(description, str):
                raise ValidationError(
                    "JSON projects can only edit their description",
                    details={"field": "description"},
                )

            def update_description(current: TaskJsonType) -> TaskJsonType:
                results.clear()
                document = deepcopy(current)
                project = self._find_typed_project(self._typed_projects(document), project_name)
                self._project_result(document, project_name)
                project["description"] = description
                results.append(self._project_result(document, project_name))
                return document

            self.__taskListProvider.updateJson(update_description)
        else:
            raise ValidationError("Unsupported project operation", details={"field": "operation_type"})
        if not results:
            raise OperationFailedError(
                "The saved project result could not be confirmed",
                effects_state="unknown",
                details={"resource": "project"},
            )
        return results[-1]

    @staticmethod
    def validate_operation_structure(
        operation_type: str,
        project_name: str,
        parameters: Mapping[str, Any],
    ) -> None:
        if not isinstance(project_name, str) or not project_name.strip():
            raise ValidationError("A project name is required", details={"field": "target"})
        if not isinstance(parameters, Mapping):
            raise ValidationError("Project parameters must be an object", details={"field": "parameters"})
        allowed = {
            "open-project": {"description"},
            "close-project": set(),
            "hold-project": set(),
            "edit-project-content": {"description"},
        }.get(operation_type)
        if allowed is None:
            raise ValidationError("Unsupported project operation", details={"field": "operation_type"})
        unknown = set(parameters) - allowed
        if unknown:
            raise ValidationError(
                "Unknown project operation parameter",
                details={"field": str(sorted(unknown, key=str)[0])},
            )
        if "description" in parameters and not isinstance(parameters["description"], str):
            raise ValidationError("description must be a string", details={"field": "description"})

    def _project_result(
        self,
        document: TaskJsonType,
        project_name: str,
        *,
        created: bool = False,
    ) -> ProjectMutationResult:
        projects = self._typed_projects(document)
        project = self._find_typed_project(projects, project_name)
        status = project.get("status")
        if not isinstance(status, str) or status not in VALID_PROJECT_STATUS:
            raise InvalidResourceDataError("Project status is invalid")
        description = project.get("description", "")
        if not isinstance(description, str):
            raise InvalidResourceDataError("Project description is invalid")
        return ProjectMutationResult(
            name=project_name,
            status=status,
            description=description,
            created=created,
        )

    @classmethod
    def _typed_projects(cls, document: TaskJsonType) -> list[dict[str, object]]:
        if not isinstance(document, dict):
            raise InvalidResourceDataError("Project data has an invalid shape")
        try:
            return cls.__get_projects(document)
        except (TypeError, ValueError) as error:
            raise InvalidResourceDataError("Project data has an invalid shape") from error

    @classmethod
    def _find_typed_project(
        cls,
        projects: list[dict[str, object]],
        name: str,
    ) -> dict[str, object]:
        try:
            return cls.__find_project(projects, name)
        except LookupError as error:
            raise ResourceNotFoundError("No project matches this name") from error
        except ValueError as error:
            raise AmbiguousResourceError("More than one project has this name") from error

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
                return stripDoc(str(self.commands[command].__doc__))
            else:
                return f"Command {command} not found"
        return stripDoc(str(self._get_help.__doc__))

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
            retval.append(f"{(i + 1):02d}: {project['name'].strip().replace(' ', '_')}")

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
        description = " ".join(messageArgs[1:])

        def update(current: TaskJsonType) -> TaskJsonType:
            document = deepcopy(current)
            project = self.__find_project(self.__get_projects(document), projName)
            project["description"] = description
            return document

        self.__taskListProvider.updateJson(update)
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
        def update(current: TaskJsonType) -> TaskJsonType:
            document = deepcopy(current)
            project = self.__find_project(self.__get_projects(document), project_name)
            project["status"] = new_status
            return document

        self.__taskListProvider.updateJson(update)
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

        def update(current: TaskJsonType) -> TaskJsonType:
            document = deepcopy(current)
            projects = self.__get_projects(document)
            matches = [project for project in projects if project.get("name") == project_name]
            if len(matches) > 1:
                raise ValueError(f"More than one project is named {project_name}")
            if matches:
                matches[0]["status"] = "open"
            else:
                projects.append({
                    "name": project_name,
                    "description": project_description,
                    "status": "open"
                })
                cast(dict[str, Any], document)["projects"] = projects
            return document

        self.__taskListProvider.updateJson(update)
        return f"Project {project_name} is now open"

    @staticmethod
    def __get_projects(document: TaskJsonType) -> list[dict[str, object]]:
        projects = document.get("projects", [])
        if not isinstance(projects, list):
            raise TypeError("Task data attribute 'projects' must be a list")
        if any(not isinstance(project, dict) for project in projects):
            raise TypeError("Every project record must be an object")
        return cast(list[dict[str, object]], projects)

    @staticmethod
    def __find_project(projects: list[dict[str, object]], name: str) -> dict[str, object]:
        matches = [project for project in projects if project.get("name") == name]
        if not matches:
            raise LookupError(f"Project {name} not found")
        if len(matches) > 1:
            raise ValueError(f"More than one project is named {name}")
        return matches[0]

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
