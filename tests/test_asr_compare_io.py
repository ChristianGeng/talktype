"""bench/asr_compare.py around the scoring (#47): engines, WAVs, record, evaluate.

No models or microphone: engines and recording are replaced by fakes.
"""

import csv
import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest
from scipy.io import wavfile

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location(
    "asr_compare", ROOT / "bench" / "asr_compare.py"
)
ac = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ac)


def test_engine_names_are_checked():
    assert ac.engine_names(" nemotron, parakeet ") == ["nemotron", "parakeet"]
    for bad in ("nemotron,parakeat", ""):
        with pytest.raises(SystemExit, match="unknown engine"):
            ac.engine_names(bad)


def test_read_wav_takes_16_bit_and_float_and_rejects_other_rates(tmp_path):
    wavfile.write(tmp_path / "a.wav", 16000, np.full(160, 16384, np.int16))
    audio, rate = ac.read_wav(tmp_path / "a.wav")
    assert rate == 16000 and audio[0] == pytest.approx(0.5)
    wavfile.write(tmp_path / "b.wav", 16000, np.full(160, 0.25, np.float32))
    assert ac.read_wav(tmp_path / "b.wav")[0][0] == pytest.approx(0.25)
    wavfile.write(tmp_path / "c.wav", 44100, np.zeros(441, np.int16))
    with pytest.raises(SystemExit, match="16 kHz"):
        ac.read_wav(tmp_path / "c.wav")


def test_record_resumes_instead_of_overwriting(tmp_path, monkeypatch):
    (tmp_path / "01.wav").write_bytes(b"keep")
    answers = iter(["", "q"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    monkeypatch.setattr(ac, "record_one", lambda: np.zeros(1600, np.float32))
    ac.record(tmp_path)
    assert (tmp_path / "01.wav").read_bytes() == b"keep"
    assert (tmp_path / "02.wav").exists() and (tmp_path / "02.json").exists()
    assert not (tmp_path / "03.wav").exists()


def test_evaluate_scores_and_writes_the_csv(tmp_path, monkeypatch, capsys):
    wavfile.write(tmp_path / "01.wav", 16000, np.zeros(16000, np.int16))
    (tmp_path / "01.json").write_text(
        json.dumps({"lang": "en", "text": "The onnx model loads.", "terms": ["onnx"]})
    )
    monkeypatch.setattr(
        ac,
        "engines",
        lambda names: {"fake": lambda audio, lang: "the onyx model loads"},
    )
    monkeypatch.setattr(
        ac,
        "load_replacer",
        lambda: ac.replacements.Replacer(ac.replacements.parse({"onyx": "onnx"})),
    )
    ac.evaluate(tmp_path, ["nemotron"])
    with open(tmp_path / "results.csv", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["hyp_replaced"] == "the onnx model loads"
    assert (rows[0]["edits"], rows[0]["edits_replaced"]) == ("1", "0")
    out = capsys.readouterr().out
    assert "fake" in out and "25.0%" in out and "0.0%" in out and "1/1" in out
