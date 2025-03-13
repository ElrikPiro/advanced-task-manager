def stripDoc(docstring: str) -> str:
    """
    Strip the leading whitespace from the docstring.

    Args:
        docstring (str): The docstring
    Returns:
        str: The docstring without leading whitespace
    """
    sanitizedDocstring = docstring.strip()
    if not sanitizedDocstring:
        return sanitizedDocstring

    lines = docstring.splitlines()
    indent = len(docstring)
    for line in lines[1:]:
        stripped = line.lstrip()
        if stripped:
            indent = min(indent, len(line) - len(stripped))

    return "\n".join(line[indent:] for line in lines)