import base64
import re
from importlib.resources import files
from pathlib import Path

from toad.acp import protocol
from toad.prompt.extract import extract_paths_from_prompt
from toad.prompt.resource import load_resource, ResourceError


def build(project_path: Path, prompt: str) -> list[protocol.ContentBlock]:
    """Build the prompt structure and extract paths with the @ syntax.

    Args:
        project_path: The project root.
        prompt: The prompt text.

    Returns:
        A list of content blocks.
    """
    prompt_content: list[protocol.ContentBlock] = []

    prompt_content.append({"type": "text", "text": prompt})
    if re.match(
        r"^(?:[$/]canon-start(?:\s|$)|(?:please\s+)?(?:use|run|resume)\s+"
        r"(?:the\s+)?canon-start(?:\s|[.!]|$))",
        prompt.strip(), re.IGNORECASE,
    ):
        note = files("toad.data").joinpath("strategy-selection.md").read_text("utf-8")
        prompt_content.append({"type": "text", "text": note})
    for path, _, _ in extract_paths_from_prompt(prompt):
        if path.endswith("/"):
            continue
        try:
            resource = load_resource(project_path, Path(path))
        except ResourceError:
            # TODO: How should this be handled?
            continue
        uri = f"file://{resource.path.absolute().resolve()}"
        if resource.text is not None:
            prompt_content.append(
                {
                    "type": "resource",
                    "resource": {
                        "uri": uri,
                        "text": resource.text,
                        "mimeType": resource.mime_type,
                    },
                }
            )
        elif resource.data is not None:
            prompt_content.append(
                {
                    "type": "resource",
                    "resource": {
                        "uri": uri,
                        "blob": base64.b64encode(resource.data).decode("utf-8"),
                        "mimeType": resource.mime_type,
                    },
                }
            )

    return prompt_content
