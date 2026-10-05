from typing import Any, Callable, List, Mapping, cast
import re
import os
from uuid import uuid4

from .MutationCoordinator import MutationCoordinator
from .Utils import stripDoc
from .Interfaces.IProjectManager import IProjectManager, ProjectCommands
from .Interfaces.ITaskJsonProvider import VALID_PROJECT_STATUS
from .Interfaces.ITaskProvider import ITaskProvider
from .Interfaces.IFileBroker import IFileBroker, VaultRegistry
from .domain.errors import (
    AmbiguousResourceError,
    DomainError,
    InvalidResourceDataError,
    OperationFailedError,
    ResourceConflictError,
    ResourceNotFoundError,
    ResourceReadError,
    ValidationError,
)
from .domain.models import ProjectMutationResult


class ObsidianProjectManager(IProjectManager):
    """
    Implementation of the project manager interface.
    Handles project management operations and processes commands.
    """

    _MUTATING_COMMANDS = frozenset({
        ProjectCommands.EDIT.value,
        ProjectCommands.ADD.value,
        ProjectCommands.REMOVE.value,
        ProjectCommands.OPEN.value,
        ProjectCommands.CLOSE.value,
        ProjectCommands.HOLD.value,
    })

    def __init__(
        self,
        taskListProvider: ITaskProvider,
        fileBroker: IFileBroker,
        mutation_coordinator: Any | None = None,
    ) -> None:
        """
        Initialize the ProjectManager with an empty projects dictionary.
        """
        self.__taskListProvider = taskListProvider
        self.__fileBroker = fileBroker
        candidates = [
            getattr(source, "mutation_coordinator", None)
            for source in (taskListProvider, fileBroker)
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
        self.commands: dict[str, Callable[[list[str]], str]] = {
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
        if command not in ProjectCommands.values():
            return self._get_help()
        arguments = list(messageArgs)
        if command in self.commands and command in self._MUTATING_COMMANDS and self.mutation_coordinator is not None:
            handler = self.commands[command]
            intent = ("project-command", command, tuple(arguments))
            return cast(
                str,
                self.mutation_coordinator.run_operation(
                    uuid4(),
                    intent,
                    lambda admitted: handler(list(admitted[2])),
                ),
            )
        return self.commands.get(command, self._get_help)(arguments)

    def perform_operation(
        self,
        operation_type: str,
        project_name: str,
        parameters: Mapping[str, Any],
    ) -> ProjectMutationResult:
        """Apply a typed project change and return the saved project data."""
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
        if operation_type == "open-project":
            return self._open_typed_project(project_name, parameters)
        project = self._find_typed_project(project_name)
        if operation_type in {"close-project", "hold-project"}:
            status = "closed" if operation_type == "close-project" else "on-hold"
            return self._update_typed_project_lines(
                str(project["path"]),
                project_name,
                lambda lines: self._replace_project_status(lines, project_name, status),
            )
        if operation_type == "edit-project-content":
            if "description" in parameters:
                raise ValidationError(
                    "Markdown projects require a line action",
                    details={"field": "action"},
                )
            action = parameters["action"]
            line_number = parameters.get("line", parameters.get("position"))
            content = parameters.get("content")
            return self._update_typed_project_lines(
                str(project["path"]),
                project_name,
                lambda lines: self._edit_project_content(
                    lines,
                    project_name,
                    action,
                    line_number,
                    content,
                ),
            )
        raise ValidationError("Unsupported project operation", details={"field": "operation_type"})

    def _update_typed_project_lines(
        self,
        project_path: str,
        project_name: str,
        updater: Callable[[list[str]], list[str]],
    ) -> ProjectMutationResult:
        results: list[ProjectMutationResult] = []

        def update(lines: list[str]) -> list[str]:
            results.clear()
            try:
                updated = updater(lines)
                status = self._typed_project_status(updated, project_name)
                result = ProjectMutationResult(
                    name=project_name,
                    status=status,
                    content="".join(updated),
                )
            except DomainError:
                raise
            except (FileNotFoundError, ValueError) as error:
                raise InvalidResourceDataError("Project file data is invalid") from error
            results.append(result)
            return updated

        saved_lines = self.__fileBroker.updateVaultFileLines(
            VaultRegistry.OBSIDIAN,
            project_path,
            update,
        )
        if not results:
            raise OperationFailedError(
                "The saved project result could not be confirmed",
                effects_state="unknown",
                details={"resource": "project"},
            )
        return ProjectMutationResult(
            name=results[-1].name,
            status=results[-1].status,
            content="".join(saved_lines),
        )

    @staticmethod
    def _typed_project_status(lines: list[str], project_name: str) -> str:
        try:
            status_line = ObsidianProjectManager.__validate_project_file(lines, project_name)
        except (FileNotFoundError, ValueError) as error:
            raise InvalidResourceDataError("Project file data is invalid") from error
        match = re.match(r"^\s*project\s*:\s*(.*?)\s*(?:\r?\n)?$", lines[status_line])
        if match is None or match.group(1) not in VALID_PROJECT_STATUS:
            raise InvalidResourceDataError("Project status is invalid")
        return match.group(1)

    def _open_typed_project(
        self,
        project_name: str,
        parameters: Mapping[str, Any],
    ) -> ProjectMutationResult:
        description = parameters.get("description", "")
        self._validate_project_name(project_name)
        projects = self._load_typed_projects()
        matches = [project for project in projects if project.get("name") == project_name]
        if len(matches) > 1:
            raise AmbiguousResourceError("More than one project has this name")
        if matches:
            project = self._validate_typed_project(matches[0], project_name)
            return self._update_typed_project_lines(
                str(project["path"]),
                project_name,
                lambda lines: self._replace_project_status(lines, project_name, "open"),
            )

        lines = [
            "---\n",
            "project: open\n",
            "---\n",
            f"# {project_name}\n",
            "\n",
            "## Description\n",
            "\n",
        ]
        if description:
            lines.extend(description.splitlines(keepends=True))
            if not lines[-1].endswith(("\n", "\r")):
                lines[-1] += "\n"
        lines.extend(["\n", "## Tasks\n", "\n"])
        project_path = f"{project_name}.md"
        created = self.__fileBroker.createVaultFileLinesIfAbsent(
            VaultRegistry.OBSIDIAN,
            project_path,
            lines,
        )
        if not created:
            raise ResourceConflictError("A vault file already exists at the requested project path")
        return ProjectMutationResult(
            name=project_name,
            status="open",
            description=description,
            content="".join(lines),
            created=True,
        )

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
        if operation_type == "open-project":
            allowed = {"description"}
        elif operation_type in {"close-project", "hold-project"}:
            allowed = set()
        elif operation_type == "edit-project-content":
            allowed = {"action", "line", "position", "content"}
        else:
            raise ValidationError("Unsupported project operation", details={"field": "operation_type"})
        unknown = set(parameters) - allowed
        if unknown:
            raise ValidationError(
                "Unknown project operation parameter",
                details={"field": str(sorted(unknown, key=str)[0])},
            )
        if operation_type == "open-project":
            if "description" in parameters and not isinstance(parameters["description"], str):
                raise ValidationError("description must be a string", details={"field": "description"})
            ObsidianProjectManager._validate_project_name(project_name)
        elif operation_type == "edit-project-content":
            action = parameters.get("action")
            if not isinstance(action, str) or action not in {"replace", "insert", "delete"}:
                raise ValidationError("Invalid project content action", details={"field": "action"})
            if "line" in parameters and "position" in parameters:
                raise ValidationError("Supply line or position, not both", details={"field": "line"})
            line = parameters.get("line", parameters.get("position"))
            if type(line) is not int or line < 1:
                raise ValidationError("A positive line or position is required", details={"field": "line"})
            if action in {"replace", "insert"} and not isinstance(parameters.get("content"), str):
                raise ValidationError("content is required", details={"field": "content"})
            if action == "delete" and "content" in parameters:
                raise ValidationError("delete does not accept content", details={"field": "content"})

    @staticmethod
    def _validate_project_name(project_name: str) -> None:
        if project_name in {".", ".."} or os.path.basename(project_name) != project_name or "/" in project_name or "\\" in project_name or "\x00" in project_name:
            raise ValidationError("Project name contains an invalid path", details={"field": "target"})

    def _find_typed_project(self, project_name: str) -> dict[str, Any]:
        projects = self._load_typed_projects()
        matches = [project for project in projects if project.get("name") == project_name]
        if not matches:
            raise ResourceNotFoundError("No project matches this name")
        if len(matches) > 1:
            raise AmbiguousResourceError("More than one project has this name")
        project = matches[0]
        return self._validate_typed_project(project, project_name)

    @staticmethod
    def _validate_typed_project(project: dict[str, Any], project_name: str) -> dict[str, Any]:
        if not isinstance(project.get("name"), str) or project["name"] != project_name:
            raise InvalidResourceDataError("Project data has an invalid shape")
        if not isinstance(project.get("path"), str) or not isinstance(project.get("status"), str):
            raise InvalidResourceDataError("Project data has an invalid shape")
        if project["status"] not in VALID_PROJECT_STATUS:
            raise InvalidResourceDataError("Project status is invalid")
        return project

    def _load_typed_projects(self) -> list[dict[str, Any]]:
        try:
            projects = self.__taskListProvider.getTaskListAttribute("projects")
        except DomainError:
            raise
        except Exception as error:
            raise ResourceReadError("Project data could not be read") from error
        if not isinstance(projects, list) or any(not isinstance(project, dict) for project in projects):
            raise InvalidResourceDataError("Project data has an invalid shape")
        return projects

    def _replace_project_status(self, lines: list[str], project_name: str, status: str) -> list[str]:
        updated = list(lines)
        status_line = self.__validate_project_file(updated, project_name)
        source = updated[status_line]
        match = re.match(r"^(\s*project\s*:\s*)(.*?)(\r?\n)?$", source)
        if match is None:
            raise InvalidResourceDataError("Project status line is invalid")
        updated[status_line] = f"{match.group(1)}{status}{match.group(3) or ''}"
        return updated

    def _edit_project_content(
        self,
        lines: list[str],
        project_name: str,
        action: str,
        line_number: int,
        content: str | None,
    ) -> list[str]:
        updated = list(lines)
        self.__validate_project_file(updated, project_name)
        closing = next(
            (index for index in range(1, len(updated)) if updated[index].strip() == "---"),
            None,
        )
        if closing is None:
            raise InvalidResourceDataError("Project frontmatter is incomplete")
        first_body_line = closing + 2
        if action == "insert":
            if line_number < first_body_line or line_number > len(updated) + 1:
                raise ValidationError("Project content position is out of range", details={"field": "line"})
            ending = "\r\n" if updated and updated[-1].endswith("\r\n") else "\n"
            line = content or ""
            if not line.endswith(("\n", "\r")):
                line += ending
            updated.insert(line_number - 1, line)
            return updated
        if line_number < first_body_line or line_number > len(updated):
            raise ValidationError("Project content line is out of range", details={"field": "line"})
        if action == "delete":
            updated.pop(line_number - 1)
            return updated
        if action == "replace":
            ending = "\r\n" if updated[line_number - 1].endswith("\r\n") else "\n"
            replacement = content or ""
            if updated[line_number - 1].endswith(("\n", "\r")):
                replacement += ending
            updated[line_number - 1] = replacement
            return updated
        raise ValidationError("Unsupported project content action", details={"field": "action"})

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
            retval.append(f"{(i + 1):02d}: {project['name'].strip().replace(' ', '_')}")

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
            lines[i] = f"{(i + 1):03d}: {line}"
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
        newContent = " ".join(messageArgs[2:])

        def update(lines: list[str]) -> list[str]:
            self.__validate_project_file(lines, fileName)
            if lineNumber < 1 or lineNumber > len(lines):
                raise ValueError(f"Line number {lineNumber} out of range. File has {len(lines)} lines.")
            updated = list(lines)
            ending = "\r\n" if updated[lineNumber - 1].endswith("\r\n") else "\n"
            updated[lineNumber - 1] = newContent + ending if updated[lineNumber - 1].endswith(("\n", "\r")) else newContent
            return updated

        self.__fileBroker.updateVaultFileLines(VaultRegistry.OBSIDIAN, projectPath, update)
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
        newContent = " ".join(messageArgs[2:])

        def update(lines: list[str]) -> list[str]:
            self.__validate_project_file(lines, fileName)
            if lineNumber < 1 or lineNumber > len(lines) + 1:
                raise ValueError(f"Line number {lineNumber} out of range. File has {len(lines)} lines.")
            updated = list(lines)
            ending = "\r\n" if updated and updated[-1].endswith("\r\n") else "\n"
            updated.insert(lineNumber - 1, newContent + ending)
            return updated

        self.__fileBroker.updateVaultFileLines(VaultRegistry.OBSIDIAN, projectPath, update)
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

        def update(lines: list[str]) -> list[str]:
            self.__validate_project_file(lines, fileName)
            if lineNumber < 1 or lineNumber > len(lines):
                raise ValueError(f"Line number {lineNumber} out of range. File has {len(lines)} lines.")
            updated = list(lines)
            updated.pop(lineNumber - 1)
            return updated

        self.__fileBroker.updateVaultFileLines(VaultRegistry.OBSIDIAN, projectPath, update)
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
        stored_status = "on-hold" if new_status == "hold" else new_status

        def update(lines: list[str]) -> list[str]:
            updated = list(lines)
            status_line = self.__validate_project_file(updated, project_name)
            source = updated[status_line]
            match = re.match(r"^(\s*project\s*:\s*)(.*?)(\r?\n)?$", source)
            if match is None:
                raise ValueError(f"Project {project_name} status line is invalid")
            updated[status_line] = f"{match.group(1)}{stored_status}{match.group(3) or ''}"
            return updated

        self.__fileBroker.updateVaultFileLines(VaultRegistry.OBSIDIAN, project_path, update)
        return f"Project {project_name} is now {new_status}"

    @staticmethod
    def __validate_project_file(lines: list[str], project_name: str) -> int:
        if not lines:
            raise FileNotFoundError(f"Project {project_name} is missing or empty")
        if lines[0].strip() != "---":
            raise FileNotFoundError(f"Project {project_name} no longer has project frontmatter")
        closing = next((index for index in range(1, len(lines)) if lines[index].strip() == "---"), None)
        if closing is None:
            raise ValueError(f"Project {project_name} frontmatter is incomplete")
        status_line = next(
            (index for index in range(1, closing) if re.match(r"^\s*project\s*:", lines[index])),
            None,
        )
        if status_line is None:
            raise FileNotFoundError(f"Project {project_name} no longer has a project status")
        status_match = re.match(r"^\s*project\s*:\s*(.*?)\s*(?:\r?\n)?$", lines[status_line])
        if status_match is None or status_match.group(1) not in VALID_PROJECT_STATUS:
            raise FileNotFoundError(f"Project {project_name} no longer has a valid project status")
        return status_line

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
            created = self.__fileBroker.createVaultFileLinesIfAbsent(
                VaultRegistry.OBSIDIAN,
                project_path,
                content,
            )
            if not created:
                raise FileExistsError(f"A vault file already exists at {project_path}")

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
