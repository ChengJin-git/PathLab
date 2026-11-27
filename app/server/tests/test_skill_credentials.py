from backend.autoresearch.engine import runtime, skill_credentials


def test_only_declared_credentials_reach_sandbox_without_env_interpolation(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        skill_credentials.Config, "get_autoresearch_dir", lambda: tmp_path
    )
    directory = tmp_path / "credentials"
    directory.mkdir()
    (directory / "skills.env").write_text(
        "PUBMED_EMAIL=research@example.org\nPADDLE_OCR_TOKEN=${SECRET}\nDATABASE_URL=private\n"
    )
    monkeypatch.setenv("SECRET", "must-not-expand")
    monkeypatch.setenv("NCBI_API_KEY", "operator-key")
    values = skill_credentials.skill_environment()
    assert values["PUBMED_EMAIL"] == "research@example.org"
    assert values["PADDLE_OCR_TOKEN"] == "${SECRET}"
    assert values["NCBI_API_KEY"] == "operator-key"
    assert "DATABASE_URL" not in values and "SECRET" not in values


def test_publisher_credentials_are_mounted_read_only_outside_workspace(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(runtime.Config, "get_autoresearch_dir", lambda: tmp_path)
    monkeypatch.setattr(runtime.Config, "get_uploads_dir", lambda: tmp_path)
    image = tmp_path / "image.sif"
    image.touch()
    monkeypatch.setattr(runtime, "_resolve_default_image", lambda: str(image))
    monkeypatch.setattr(runtime, "_resolve_apptainer_bin", lambda: "apptainer")
    publishers = tmp_path / "credentials/lit-dl"
    publishers.mkdir(parents=True)
    root = tmp_path / "session_test"
    root.mkdir()
    command = runtime.sandbox_command(root, {})
    assert f"{publishers}:/opt/pathlab/lit-dl:ro" in command
    assert (
        skill_credentials.skill_environment()["LIT_DL_CONFIG_DIR"]
        == "/opt/pathlab/lit-dl"
    )
    assert not list(root.rglob("*credentials*"))
