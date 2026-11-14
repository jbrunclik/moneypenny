"""Checklist items of an artifact page and their saved ticks
(src/agent/tools/artifact_checklist.py; keys match web/src/artifact/bridge-client.ts)."""

from src.agent.tools.artifact_checklist import checklist_items, checklist_status


def _page(*labels: str) -> str:
    items = "".join(f'<li><label><input type="checkbox"> {label}</label></li>' for label in labels)
    return f'<div class="mp-card"><ul class="mp-checklist">{items}</ul></div>'


def test_items_are_label_texts_with_repeats_numbered() -> None:
    assert checklist_items(_page("Milk", "Eggs", "Eggs")) == ["Milk", "Eggs", "Eggs #2"]


def test_nested_label_markup_keys_by_its_text() -> None:
    html = '<ul class="mp-checklist"><li><label><input type=checkbox> <b>Milk</b>  2 l</label></li></ul>'
    assert checklist_items(html) == ["Milk 2 l"]


def test_checkboxes_outside_a_checklist_are_not_items() -> None:
    html = '<label><input type="checkbox"> Dark mode</label>' + _page("Milk")
    assert checklist_items(html) == ["Milk"]


def test_status_splits_done_and_open_in_page_order() -> None:
    state = {"app": None, "checklist": {"Bread": True}}
    assert checklist_status(_page("Milk", "Bread", "Eggs"), state) == {
        "done": ["Bread"],
        "open": ["Milk", "Eggs"],
    }


def test_a_reworded_item_loses_only_its_own_tick() -> None:
    state = {"checklist": {"Milk": True, "Bread": True}}
    assert checklist_status(_page("Milk", "Rye bread"), state) == {
        "done": ["Milk"],
        "open": ["Rye bread"],
    }


def test_state_without_ticks_leaves_everything_open() -> None:
    for state in (None, {"score": 3}, {"app": {"score": 3}}):
        assert checklist_status(_page("Milk"), state) == {"done": [], "open": ["Milk"]}


def test_a_page_without_a_checklist_has_no_status() -> None:
    assert checklist_status("<p>Tip calculator</p>", {"checklist": {"Milk": True}}) is None
