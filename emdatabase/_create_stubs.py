"""Generate ``data/__init__.pyi`` so an IDE can complete the dataset classes.

The classes in :mod:`emdatabase.data` are built at import time from the YAML,
so nothing static knows their names. The stub is that list, written out. It is
generated from the same files the loader reads, and CI runs ``--check`` to fail
if the committed stub has drifted from them.
"""

import sys
from pathlib import Path

import yaml

from emdatabase.metadata import dataset_files

STUB_PATH = Path(__file__).parent / "data" / "__init__.pyi"


def build_docstring(dataset_dict) -> str:
    """Build a docstring for the dataset from its metadata."""
    doc = ""
    if dataset_dict.get("description"):
        doc += f"{dataset_dict['description']}\n\n"
    if dataset_dict.get("doi"):
        doc += f"    DOI: {dataset_dict['doi']}\n\n"
    if dataset_dict.get("license"):
        doc += f"    License: {dataset_dict['license']}\n\n"

    what = "these model weights" if dataset_dict.get("kind") == "weights" else "this dataset"
    doc += f"    You can download {what} here:\n"
    doc += f"    {dataset_dict.get('url') or dataset_dict['source']}\n\n"
    return doc


def build_pyi_stub() -> str:
    """The contents of the ``.pyi`` stub for the current dataset YAML."""
    stub_lines = [
        "# Auto-generated stub file for emdatabase",
        "from emdatabase.downloadable_dataset import DownloadableDataset",
        "",
    ]

    dataset_classes = []

    for dataset_path in dataset_files():
        data_dict_yaml = yaml.safe_load(dataset_path.read_text(encoding="utf-8"))
        for name in data_dict_yaml:
            data_dict = data_dict_yaml[name]
            class_name = name.replace(" ", "_").replace("-", "_")
            description = build_docstring(data_dict)

            stub_lines.append(f"class {class_name}(DownloadableDataset):")
            stub_lines.append('    """')
            stub_lines.append(f"    {name}")
            if description:
                stub_lines.append("")
                stub_lines.append(f"    {description}")
            stub_lines.append('    """')
            stub_lines.append("    ...")
            stub_lines.append("")

            dataset_classes.append(class_name)

    stub_lines.append(f"__all__ = {dataset_classes}")
    return "\n".join(stub_lines)


def generate_pyi_stub() -> None:
    """Write the stub file."""
    STUB_PATH.write_text(build_pyi_stub(), encoding="utf-8")


if __name__ == "__main__":
    if "--check" in sys.argv:
        if STUB_PATH.read_text(encoding="utf-8") != build_pyi_stub():
            sys.exit(
                f"{STUB_PATH} is out of date with the dataset YAML; "
                "regenerate it with `python -m emdatabase._create_stubs`"
            )
    else:
        generate_pyi_stub()
