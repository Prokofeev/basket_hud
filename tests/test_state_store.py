from broadcast_control.models.schemas import GraphicState, PlayerState
from broadcast_control.state.store import JsonStateStore


def test_state_store_roundtrip_and_last_good(tmp_path):
    store = JsonStateStore(tmp_path)
    state = GraphicState(phase="preview_ready", player=PlayerState(name="Tester", visible=True))

    store.write("preview_state", state)
    snapshot = store.read("preview_state", GraphicState, max_age_s=60)

    assert snapshot.value.phase == "preview_ready"
    assert snapshot.value.player.name == "Tester"
    assert snapshot.source == "current"
    assert (tmp_path / "preview_state.last_good.json").exists()


def test_state_store_falls_back_to_last_good(tmp_path):
    store = JsonStateStore(tmp_path)
    store.write("live_state", GraphicState(phase="on_air_synced", player=PlayerState(name="Live")))
    (tmp_path / "live_state.json").write_text("{bad json", encoding="utf-8")

    snapshot = store.read("live_state", GraphicState)

    assert snapshot.source == "last_good"
    assert snapshot.value.player.name == "Live"

