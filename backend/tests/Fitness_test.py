import unittest
import os
import ast


def calculate_modularity_fitness(modules, dependencies):
    """
    Calculate modularity fitness score based on modules and their dependencies.

    Parameters:
    - modules: list of module names
    - dependencies: dict mapping module names to lists of modules they depend on

    Returns:
    - A score between 0 and 1, where higher values indicate better modularity
    """
    if not modules:
        return 0.0

    # Calculate cohesion (fewer external dependencies is better)
    total_possible_dependencies = len(modules) * (len(modules) - 1)
    if total_possible_dependencies == 0:
        return 1.0  # Only one module, perfectly modular by default

    actual_dependencies = sum(len(deps) for deps in dependencies.values())

    # Calculate coupling ratio (lower is better)
    coupling_ratio = actual_dependencies / total_possible_dependencies

    # Convert to fitness score (higher is better)
    modularity_score = 1.0 - coupling_ratio

    return modularity_score


class FintnessFunctions(unittest.TestCase):

    def test_extract_modules_from_backend(self):
        """Test extracting real modules and dependencies from the backend folder."""

        def extract_modules_and_dependencies(root_dir):
            """Extract modules and their dependencies from Python files in a directory."""
            modules = []
            dependencies = {}

            # Walk through the directory
            for dirpath, _, filenames in os.walk(root_dir):
                for filename in filenames:
                    if filename.endswith(".py"):
                        rel_path = os.path.relpath(os.path.join(dirpath, filename), root_dir)
                        # Convert file path to module name
                        module_name = os.path.splitext(rel_path)[0].replace(os.sep, ".")
                        modules.append(module_name)

                        # Parse the file to find imports
                        try:
                            with open(os.path.join(dirpath, filename), 'r', encoding='utf-8') as f:
                                file_content = f.read()

                            tree = ast.parse(file_content)
                            module_deps = []

                            # Extract imports
                            for node in ast.walk(tree):
                                if isinstance(node, ast.Import):
                                    for name in node.names:
                                        module_deps.append(name.name)
                                elif isinstance(node, ast.ImportFrom):
                                    if node.module:
                                        module_deps.append(node.module)

                            dependencies[module_name] = module_deps
                        except Exception as e:
                            print(f"Error parsing {filename}: {e}")

            return modules, dependencies

        # Path to backend folder
        backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))

        # Extract modules and dependencies
        modules, dependencies = extract_modules_and_dependencies(backend_dir)

        # Check if we found any modules
        self.assertTrue(len(modules) > 0, "No modules found in backend directory")

        # Calculate and display modularity score
        modularity_score = calculate_modularity_fitness(modules, dependencies)
        print(f"Backend Modularity Score: {modularity_score:.4f}")
        self.assertTrue(0.8 <= modularity_score, "Modularity below threshold")


if __name__ == "__main__":
    unittest.main()
