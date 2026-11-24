"""The current message's attachments carry their history ids, so the model
can hand one to execute_code or save it with manage_documents."""

import base64

from src.agent.message_content import annotate_history_file_ids, build_message_content


def test_listing_names_ids_for_code_and_saving() -> None:
    files = [
        {"name": "lease.pdf", "type": "application/pdf", "data": base64.b64encode(b"%PDF").decode()}
    ]
    annotate_history_file_ids("msg-1", files)  # type: ignore[arg-type]

    blocks = build_message_content("keep this", files)  # type: ignore[arg-type]

    assert isinstance(blocks, list)
    listing = blocks[-1]["text"]
    assert "lease.pdf (id msg-1:0)" in listing
    assert "execute_code" in listing
    assert "manage_documents" in listing
