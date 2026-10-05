"""Compare the speech engines on your own voice (#47).

    uv run --extra local --extra parakeet --extra nemotron \
        bench/asr_compare.py record ~/talktype-bench
    uv run --extra local --extra parakeet --extra nemotron \
        bench/asr_compare.py evaluate ~/talktype-bench

`record` shows the sentences from bench/sentences.yaml one at a time and saves
each reading as NN.wav with its reference in NN.json. `evaluate` runs every
recording through Nemotron as TalkType streams it, Parakeet over the whole
recording and faster-whisper base and small, and prints word error rate,
vocabulary terms right and real-time factor, with and without the config's
replacements. Recordings stay where you put them, outside the repository.
"""

import argparse
import csv
import json
import re
import sys
import time
from pathlib import Path

import numpy as np
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import replacements  # noqa: E402

SAMPLE_RATE = 16000
SENTENCES = Path(__file__).with_name("sentences.yaml")
CONFIG = Path.home() / ".config" / "talktype" / "config.yaml"

# Words, keeping inner hyphens and apostrophes: "onnx-asr", "let's".
_WORD = re.compile(r"\w+(?:['’-]\w+)*")


def words(text: str) -> list[str]:
    """Normalised words for scoring: lower case, punctuation dropped."""
    return [w.replace("’", "'") for w in _WORD.findall(text.lower())]


def edit_distance(ref: list[str], hyp: list[str]) -> int:
    """Word-level Levenshtein distance (substitutions, insertions, deletions)."""
    row = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        prev, row[0] = row[0], i
        for j, h in enumerate(hyp, 1):
            prev, row[j] = row[j], min(row[j] + 1, row[j - 1] + 1, prev + (r != h))
    return row[-1]


def term_found(term: str, hyp: list[str]) -> bool:
    """Whether the term's words occur contiguously in the hypothesis."""
    t = words(term)
    return any(hyp[i : i + len(t)] == t for i in range(len(hyp) - len(t) + 1))


def load_sentences(path: Path = SENTENCES) -> list[dict]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))["sentences"]


def load_replacer(path: Path = CONFIG) -> replacements.Replacer:
    """The config's replacement list, or an empty one."""
    try:
        config = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except OSError:
        config = {}
    return replacements.Replacer(replacements.parse(config.get("replacements")))


# --- record ------------------------------------------------------------------


def record_one() -> np.ndarray:
    """Record from the default microphone between two presses of Enter."""
    import sounddevice as sd

    blocks = []
    with sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype="float32",
        callback=lambda data, frames, t, status: blocks.append(data.copy()),
    ):
        input("  recording... press Enter when done ")
    return np.concatenate(blocks).ravel() if blocks else np.zeros(0, np.float32)


def record(out: Path):
    from scipy.io import wavfile

    out.mkdir(parents=True, exist_ok=True)
    sentences = load_sentences()
    print(f"{len(sentences)} sentences. Read each one at your normal pace.")
    print("Enter starts and stops; 'r' + Enter repeats the last; 'q' quits.\n")
    n = 0
    while n < len(sentences):
        s = sentences[n]
        name = out / f"{n + 1:02d}"
        print(f"[{n + 1}/{len(sentences)}] ({s['lang']})  {s['text']}")
        answer = input("  press Enter to start ").strip().lower()
        if answer == "q":
            break
        if answer == "r" and n:
            n -= 1
            continue
        audio = record_one()
        wavfile.write(
            f"{name}.wav", SAMPLE_RATE, (np.clip(audio, -1, 1) * 32767).astype(np.int16)
        )
        Path(f"{name}.json").write_text(
            json.dumps(s, ensure_ascii=False), encoding="utf-8"
        )
        print(f"  saved {name.name}.wav ({len(audio) / SAMPLE_RATE:.1f} s)\n")
        n += 1


# --- evaluate ----------------------------------------------------------------


def engines(names: list[str]):
    """name -> function(audio, lang) -> text, loading only what is asked for."""
    found = {}
    if "nemotron" in names:
        import nemotron

        engine = nemotron.load(cpu_threads=4)

        def stream(audio, lang):
            # As TalkType streams it: fixed chunks as they arrive, then flush.
            s = nemotron.Stream(engine, lang)
            step = int(SAMPLE_RATE * 0.05)
            text = "".join(
                s.feed(audio[i : i + step]) for i in range(0, len(audio), step)
            )
            return (text + s.flush()).strip()

        found["nemotron"] = stream
    if "parakeet" in names:
        import parakeet

        model = parakeet.load(cpu_threads=8)
        # model=model binds now: the whisper loop below reuses the name
        found["parakeet"] = lambda audio, lang, model=model: parakeet.transcribe(
            model, audio
        )
    for size in ("base", "small"):
        if f"whisper-{size}" in names:
            from faster_whisper import WhisperModel

            model = WhisperModel(size, device="cpu", compute_type="int8", cpu_threads=8)

            def whisper(audio, lang, model=model):
                segments, _ = model.transcribe(audio, language=lang, beam_size=5)
                return " ".join(seg.text.strip() for seg in segments).strip()

            found[f"whisper-{size}"] = whisper
    return found


def score(rows: list[dict], key: str) -> dict:
    """Totals for a list of result rows: WER, terms right, real-time factor."""
    edits = sum(r[f"edits{key}"] for r in rows)
    ref_words = sum(r["ref_words"] for r in rows)
    terms = sum(r["terms"] for r in rows)
    right = sum(r[f"terms_right{key}"] for r in rows)
    return {
        "wer": edits / ref_words if ref_words else 0.0,
        "terms": f"{right}/{terms}",
        "rtf": sum(r["seconds"] for r in rows)
        / max(sum(r["audio_s"] for r in rows), 1e-9),
    }


def evaluate(directory: Path, names: list[str]):
    from scipy.io import wavfile

    replacer = load_replacer()
    recordings = sorted(directory.glob("*.wav"))
    if not recordings:
        raise SystemExit(f"no recordings in {directory}")
    rows = []
    for name, transcribe in engines(names).items():
        # Warm up once, so the first recording does not carry the start-up cost.
        transcribe(np.zeros(SAMPLE_RATE, dtype=np.float32), "en")
        for wav in recordings:
            meta = json.loads(wav.with_suffix(".json").read_text(encoding="utf-8"))
            rate, data = wavfile.read(wav)
            audio = data.astype(np.float32) / 32768.0
            started = time.monotonic()
            hyp = transcribe(audio, meta["lang"])
            seconds = time.monotonic() - started
            row = {
                "id": wav.stem,
                "lang": meta["lang"],
                "engine": name,
                "ref": meta["text"],
                "hyp": hyp,
                "hyp_replaced": replacer.apply(hyp),
                "seconds": seconds,
                "audio_s": len(audio) / rate,
                "ref_words": len(words(meta["text"])),
                "terms": len(meta["terms"]),
            }
            for key, text in (("", hyp), ("_replaced", row["hyp_replaced"])):
                w = words(text)
                row[f"edits{key}"] = edit_distance(words(meta["text"]), w)
                row[f"terms_right{key}"] = sum(term_found(t, w) for t in meta["terms"])
            rows.append(row)
            print(f"  {name:14} {wav.stem} {hyp}", flush=True)
    with open(directory / "results.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(
        f"\n{'engine':14} {'lang':4} {'WER':>6} {'WER+repl':>9} {'terms':>7} {'terms+repl':>11} {'RTF':>5}"
    )
    for name in dict.fromkeys(r["engine"] for r in rows):
        for lang in sorted({r["lang"] for r in rows}):
            sel = [r for r in rows if r["engine"] == name and r["lang"] == lang]
            plain, repl = score(sel, ""), score(sel, "_replaced")
            print(
                f"{name:14} {lang:4} {plain['wer']:6.1%} {repl['wer']:9.1%} "
                f"{plain['terms']:>7} {repl['terms']:>11} {plain['rtf']:5.2f}"
            )
    print(f"\nhypotheses: {directory / 'results.csv'}")


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    rec = sub.add_parser("record", help="read the sentences aloud and save them")
    rec.add_argument("directory", type=Path)
    ev = sub.add_parser("evaluate", help="score every engine on the recordings")
    ev.add_argument("directory", type=Path)
    ev.add_argument("--engines", default="nemotron,parakeet,whisper-base,whisper-small")
    args = parser.parse_args()
    if args.command == "record":
        record(args.directory.expanduser())
    else:
        evaluate(args.directory.expanduser(), args.engines.split(","))


if __name__ == "__main__":
    main()
