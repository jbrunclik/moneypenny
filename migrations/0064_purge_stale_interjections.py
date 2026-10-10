"""Drop leftover mid-run steering entries.

Steering that arrived after a turn's last tool round was never consumed and
stayed in kv_store until the conversation's next turn - forever for deleted
conversations. Turns now clear it when they end; this removes the ones
already stranded (any turn in flight during the deploy is restarted anyway).
"""

from yoyo import step

__depends__ = {"0063_clamp_read_count_on_delete"}

steps = [
    step("DELETE FROM kv_store WHERE namespace = 'interject'"),
]
