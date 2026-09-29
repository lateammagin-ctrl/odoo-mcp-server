from odoo_mcp.skills import list_skills, get_skill


def _make_skill(dir_path, name, description, body):
    (dir_path / f"{name}.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\n{body}",
        encoding="utf-8",
    )


def test_list_skills_reads_frontmatter(tmp_path):
    _make_skill(tmp_path, "prospection", "Créer un lead", "Corps A")
    _make_skill(tmp_path, "devis", "Créer un devis", "Corps B")
    skills = list_skills(str(tmp_path))
    by_name = {s["name"]: s for s in skills}
    assert by_name["prospection"]["description"] == "Créer un lead"
    assert by_name["devis"]["description"] == "Créer un devis"


def test_get_skill_returns_full_content(tmp_path):
    _make_skill(tmp_path, "prospection", "Créer un lead", "Corps détaillé")
    content = get_skill(str(tmp_path), "prospection")
    assert "Corps détaillé" in content


def test_get_skill_unknown_raises(tmp_path):
    try:
        get_skill(str(tmp_path), "inexistant")
        assert False, "doit lever"
    except FileNotFoundError as exc:
        assert "inexistant" in str(exc)


def test_list_skills_missing_dir_returns_empty(tmp_path):
    assert list_skills(str(tmp_path / "absent")) == []


def test_repo_ships_marketing_automation_skill():
    """Le savoir-faire livré doit être lisible par le serveur (frontmatter
    valide) et porter les points qui évitent les erreurs coûteuses."""
    names = {s["name"]: s for s in list_skills("skills_library")}
    assert "campagne-marketing-automation" in names
    assert names["campagne-marketing-automation"]["description"]

    content = get_skill("skills_library", "campagne-marketing-automation")
    # Le piège principal : `domain` est calculé, c'est `activity_domain` qu'on écrit.
    assert "activity_domain" in content
    # La règle d'or doit être écrite noir sur blanc.
    assert "Start" in content
