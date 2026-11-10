"""Hilfsskripte (script.shyft_*) teilen sich mehrere shyft-Add-ons in einer HA-Instanz: Loeschen nur bei eigener
Markierung, nie beim Start (siehe sync_number_script in app.py)."""
import pytest

import app

CONTROL = "heating_target_temp"
SCRIPT_ID = app.AUTO_MANAGED_CONTROLS[CONTROL]["script_id"]


class FakeHA:
    def __init__(self, existing=None):
        self.existing = existing
        self.deleted = []
        self.put = []
        self.services = []

    def get_script_config(self, script_id):
        return self.existing

    def delete_script_config(self, script_id):
        self.deleted.append(script_id)

    def put_script_config(self, script_id, config):
        self.put.append((script_id, config))

    def call_service(self, domain, service, data=None):
        self.services.append((domain, service))


def marked(slug):
    return {"alias": "x", "description": f"Von shyft-power automatisch verwaltet. {app.SCRIPT_OWNER_PREFIX}{slug}"}


@pytest.fixture
def ha(monkeypatch):
    fake = FakeHA()
    monkeypatch.setattr(app, "homeassistant_adapter", fake)
    monkeypatch.setattr(app, "_own_script_slug", lambda: "me_shyft_addon")
    return fake


def test_startup_never_deletes(ha):
    ha.existing = marked("me_shyft_addon")
    app.sync_number_script(CONTROL, "", startup=True)
    assert ha.deleted == []


def test_empty_mapping_keeps_foreign_script(ha):
    ha.existing = marked("other_shyft_addon")
    app.sync_number_script(CONTROL, "", previous_entity_id="number.x")
    assert ha.deleted == []


def test_empty_mapping_deletes_own_script(ha):
    ha.existing = marked("me_shyft_addon")
    app.sync_number_script(CONTROL, "")
    assert ha.deleted == [SCRIPT_ID]


def test_unmarked_script_kept_if_never_mapped_here(ha):
    ha.existing = {"alias": "x"}
    app.sync_number_script(CONTROL, "")
    assert ha.deleted == []


def test_unmarked_script_deleted_if_user_cleared_mapping(ha):
    ha.existing = {"alias": "x"}
    app.sync_number_script(CONTROL, "", previous_entity_id="number.x")
    assert ha.deleted == [SCRIPT_ID]


def test_missing_script_is_noop(ha):
    ha.existing = None
    app.sync_number_script(CONTROL, "", previous_entity_id="number.x")
    assert ha.deleted == []


def test_create_marks_owner_and_heals_startup(ha):
    result = app.sync_number_script(CONTROL, "number.e3_vitocal_normaltemperatur", startup=True)
    assert result == f"script.{SCRIPT_ID}"
    script_id, config = ha.put[0]
    assert script_id == SCRIPT_ID
    assert app._script_owner(config) == "me_shyft_addon"
    assert config["sequence"][0]["target"]["entity_id"] == "number.e3_vitocal_normaltemperatur"
