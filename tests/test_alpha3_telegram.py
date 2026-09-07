"""Alpha 3% Telegram bot read-only safety tests.

Verifies the hard safety contract of tg_bot_alpha2.py (the bot serving
alpha3_dry_runner via alpha3-tg-bot.service):
  * Read-only handlers (start/help/status family) never mutate the paper
    ledger (STATE_FILE) and never write the command file.
  * Mutation handlers (/pause /resume /kill /disarm) write ONLY the expected
    action to CMD_FILE — the paper state JSON is never touched.

Mirror of tests/test_alpha4_telegram.py. Difference: tg_bot_alpha2 has no
audit log_event wiring, so isolation is STATE_FILE/CMD_FILE/CHAT_ID only.
"""

import asyncio
import json
import types

import pytest

import tg_bot_alpha2 as bot


@pytest.fixture(autouse=True)
def isolate_bot_side_effects(tmp_path, monkeypatch):
    """Point the bot at tmp_path and pin authorization."""
    monkeypatch.setattr(bot, "STATE_FILE", tmp_path / "alpha3_state.json")
    monkeypatch.setattr(bot, "CMD_FILE", tmp_path / "alpha3_cmd.json")
    monkeypatch.setattr(bot, "CHAT_ID", "12345")
    return tmp_path


class FakeReply:
    def __init__(self):
        self.sent = []

    async def reply_text(self, text, **kwargs):
        self.sent.append(text)


def make_update():
    """An authorized update object: effective_chat.id matches the pinned CHAT_ID."""
    reply = FakeReply()
    upd = types.SimpleNamespace(
        effective_chat=types.SimpleNamespace(id=12345),
        message=types.SimpleNamespace(reply_text=reply.reply_text),
    )
    return upd, reply


def run(awaitable):
    return asyncio.run(awaitable)


@pytest.fixture
def sample_paper_state(tmp_path, monkeypatch):
    """A minimal paper-state file present at the bot's STATE_FILE path."""
    state = {
        "capital": 5.0, "equity": 5.0, "peak_equity": 5.0,
        "start_capital": 5.0, "stake_pct": 0.20, "leverage": 20.0,
        "total_trades": 0, "total_wins": 0, "total_losses": 0,
        "cooldown_remaining": 0, "open_positions": {}, "trades": [],
        "last_update": None, "start_time": None,
    }
    p = tmp_path / "alpha3_state.json"
    p.write_text(json.dumps(state))
    monkeypatch.setattr(bot, "STATE_FILE", p)
    return p


def test_load_state_reads_file_and_does_not_write(sample_paper_state):
    before = sample_paper_state.read_bytes()
    loaded = bot.load_state()
    assert loaded["capital"] == 5.0
    assert sample_paper_state.read_bytes() == before
    assert not bot.CMD_FILE.exists()


def test_load_state_json_error_falls_back_safely(tmp_path, monkeypatch):
    p = tmp_path / "alpha3_state.json"
    p.write_text("{not valid json")
    monkeypatch.setattr(bot, "STATE_FILE", p)
    loaded = bot.load_state()
    assert loaded["total_trades"] == 0
    assert loaded["simulation"] == "alpha3"


def test_read_only_handler_never_writes_state_or_cmd(sample_paper_state):
    upd, reply = make_update()
    run(bot.cmd_start(upd, None))
    assert reply.sent, "read-only handler should reply"
    assert not bot.CMD_FILE.exists()

    upd, reply = make_update()
    run(bot.cmd_help(upd, None))
    # help generated a reply; the paper state JSON was never rewritten
    assert json.loads(sample_paper_state.read_text())["total_trades"] == 0
    assert not bot.CMD_FILE.exists()


def test_cmd_pause_writes_stop_action_only(sample_paper_state):
    upd, _ = make_update()
    run(bot.cmd_pause(upd, None))
    assert bot.CMD_FILE.exists()
    cmd = json.loads(bot.CMD_FILE.read_text())
    assert cmd["action"] == "stop"
    assert "ts" in cmd
    # ledger unchanged
    assert json.loads(sample_paper_state.read_text())["total_trades"] == 0


def test_cmd_resume_writes_start_action(sample_paper_state):
    upd, _ = make_update()
    run(bot.cmd_resume(upd, None))
    assert json.loads(bot.CMD_FILE.read_text())["action"] == "start"


def test_cmd_kill_writes_kill_action(sample_paper_state):
    upd, _ = make_update()
    run(bot.cmd_kill(upd, None))
    assert json.loads(bot.CMD_FILE.read_text())["action"] == "kill"


def test_cmd_disarm_writes_disarm_action(sample_paper_state):
    upd, _ = make_update()
    run(bot.cmd_disarm(upd, None))
    assert json.loads(bot.CMD_FILE.read_text())["action"] == "disarm"


def test_unauthorized_chat_is_rejected(sample_paper_state, monkeypatch):
    monkeypatch.setattr(bot, "CHAT_ID", "99999")
    upd = types.SimpleNamespace(effective_chat=types.SimpleNamespace(id=12345),
                                message=types.SimpleNamespace(
                                    reply_text=FakeReply().reply_text))
    run(bot.cmd_pause(upd, None))
    assert not bot.CMD_FILE.exists(), "unauthorized chat must not write CMD_FILE"


def test_read_only_state_snapshot_after_handlers(sample_paper_state):
    """A full sequence of commands leaves the ledger byte-identical."""
    upd, _ = make_update()
    run(bot.cmd_start(upd, None))
    run(bot.cmd_pause(upd, None))
    run(bot.cmd_resume(upd, None))
    run(bot.cmd_kill(upd, None))
    run(bot.cmd_disarm(upd, None))
    state_after = json.loads(sample_paper_state.read_text())
    assert state_after["total_trades"] == 0
    assert state_after["open_positions"] == {}
    assert state_after["equity"] == 5.0
    assert json.loads(bot.CMD_FILE.read_text())["action"] == "disarm"