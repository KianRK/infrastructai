from pathlib import Path

from app.model_store import resolve_model


def test_model_copied_from_the_registry_reports_its_registered_version(tmp_path: Path) -> None:
    model = tmp_path / "model.onnx"
    model.touch()
    (tmp_path / "registered_model_meta").write_text(
        "model_name: roadscan-detector\nmodel_version: 3\n"
    )

    assert resolve_model(str(model)).version == "roadscan-detector v3"


def test_plain_file_reports_its_name(tmp_path: Path) -> None:
    model = tmp_path / "experiment.onnx"
    model.touch()

    assert resolve_model(str(model)).version == "experiment"
