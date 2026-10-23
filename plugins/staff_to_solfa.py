"""
JARVIS plugin: staff_to_solfa

Takes either a spoken/typed list of note names (e.g. "C4:4 D4:4 E4:4 F4:4 | G4:2")
or the path to an existing .musicxml file, reads it back as tonic sol-fa relative
to a given key, and plays a short synthesized audio preview of the melody so the
user can hear what was read.

No third-party packages required — pure standard library.
"""

import re
import sys
import time
import math
import wave
import array
import shutil
import subprocess
from pathlib import Path
from xml.etree import ElementTree as ET

PLUGIN = {
    "name": "staff_to_solfa",
    "description": (
        "Reads existing staff notation — either typed note names like "
        "'C4:4 D4:4 E4:4 F4:4 | G4:2' or an existing .musicxml file — reads it back "
        "as tonic sol-fa (d r m f s l t) relative to a given key, and plays a short "
        "audio preview of the melody. Use this when the user wants to know the "
        "sol-fa for a written melody, or wants JARVIS to 'read', 'interpret', or "
        "'play' staff notation / sheet music / a music file back to them. Requires "
        "a key (e.g. C, G, D, F, Bb) — if missing, ask the user for it rather than "
        "guessing. Do NOT use this tool to write new staff notation from sol-fa — "
        "use solfa_to_staff for that instead."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "notes": {
                "type": "STRING",
                "description": (
                    "Space-separated note tokens: letter A-G, optional # or b, octave "
                    "digit, then :duration (4 quarter, 8 eighth, 2 half, 1 whole, 16 "
                    "sixteenth, add . to dot it). Rest is '-'. Bars separated by '|'. "
                    "Example: 'C4:4 D4:4 E4:4 F4:4 | G4:2 -:2'. Leave blank if using file_path instead."
                ),
            },
            "key": {
                "type": "STRING",
                "description": "The major key the melody is written in, e.g. C, G, D, A, E, B, F#, F, Bb, Eb, Ab, Db.",
            },
            "file_path": {
                "type": "STRING",
                "description": "Optional path to an existing .musicxml file to read instead of typed notes.",
            },
            "play": {
                "type": "BOOLEAN",
                "description": "Whether to play an audio preview after reading it. Defaults to true.",
            },
            "tempo": {
                "type": "NUMBER",
                "description": "Playback tempo in beats (quarter notes) per minute. Defaults to 100.",
            },
        },
        "required": [],
    },
}

# ---------------------------------------------------------------- theory ---

LETTERS = ['C', 'D', 'E', 'F', 'G', 'A', 'B']
LETTER_SEMI = {'C': 0, 'D': 2, 'E': 4, 'F': 5, 'G': 7, 'A': 9, 'B': 11}
SHARP_ORDER = ['F', 'C', 'G', 'D', 'A', 'E', 'B']
FLAT_ORDER = ['B', 'E', 'A', 'D', 'G', 'C', 'F']
SHARP_KEYS = {'C': 0, 'G': 1, 'D': 2, 'A': 3, 'E': 4, 'B': 5, 'F#': 6, 'C#': 7}
FLAT_KEYS = {'F': 1, 'Bb': 2, 'Eb': 3, 'Ab': 4, 'Db': 5, 'Gb': 6, 'Cb': 7}

NOTE_RE = re.compile(r"^(-|[A-Ga-g])(#|b)?(\d)?(?::(\d+\.?))?$")

# musicxml <type> text -> our duration code
TYPE_TO_DUR = {
    'whole': '1', 'half': '2', 'quarter': '4', 'eighth': '8',
    '16th': '16', '32nd': '32',
}
QUARTER_MAP = {'1': 4.0, '2': 2.0, '4': 1.0, '8': 0.5, '16': 0.25, '32': 0.125}


def get_key_sig(key_name):
    key_name = key_name.strip()
    key_name = key_name[0].upper() + key_name[1:] if key_name else key_name
    tonic_letter = key_name[0].upper() if key_name else 'C'
    if key_name in SHARP_KEYS:
        n = SHARP_KEYS[key_name]
        return {'tonic_letter': tonic_letter, 'type': 'sharp', 'altered': SHARP_ORDER[:n]}
    if key_name in FLAT_KEYS:
        n = FLAT_KEYS[key_name]
        return {'tonic_letter': tonic_letter, 'type': 'flat', 'altered': FLAT_ORDER[:n]}
    raise ValueError(f"'{key_name}' isn't a key I recognise — try something like C, G, D, F or Bb")


def key_sig_acc(key_sig, letter):
    if key_sig['type'] == 'sharp' and letter in key_sig['altered']:
        return 1
    if key_sig['type'] == 'flat' and letter in key_sig['altered']:
        return -1
    return 0


def note_for_degree(key_sig, base_octave, total_degree):
    tonic_idx = LETTERS.index(key_sig['tonic_letter'])
    idx = (tonic_idx + total_degree) % 7
    letter = LETTERS[idx]
    wraps = (tonic_idx + total_degree) // 7
    octave = base_octave + wraps
    return letter, key_sig_acc(key_sig, letter), octave


def abs_semitone(letter, alter, octave):
    return LETTER_SEMI[letter] + alter + 12 * octave


def to_solfa(letter, alter, octave, key_sig, base_octave=4):
    target = abs_semitone(letter, alter, octave)
    best = None
    for d in range(-21, 22):
        nl, nacc, noct = note_for_degree(key_sig, base_octave, d)
        semi = abs_semitone(nl, nacc, noct)
        diff = target - semi
        if abs(diff) <= 1 and (best is None or abs(diff) < abs(best[1])):
            best = (d, diff)
            if diff == 0:
                break
    if best is None:
        return '?'
    d, diff = best
    base_deg = d % 7
    shift_count = d // 7
    plain = ['d', 'r', 'm', 'f', 's', 'l', 't'][base_deg]
    if diff == 0:
        name = plain
    elif diff == 1:
        name = {0: 'di', 1: 'ri', 2: 'm', 3: 'fi', 4: 'si', 5: 'li', 6: 'd'}.get(base_deg, plain + '#')
    else:
        name = {0: 't', 1: 'ra', 2: 'me', 3: 'm', 4: 'se', 5: 'le', 6: 'te'}.get(base_deg, plain + 'b')
    marks = ("'" * shift_count) if shift_count > 0 else ("," * -shift_count if shift_count < 0 else '')
    return name + marks


def parse_notes(text, key_name, base_octave=4):
    key_sig = get_key_sig(key_name)
    bars = [b.strip() for b in text.strip().split('|') if b.strip()]
    if not bars:
        raise ValueError("no notes found")
    last_dur = '4'
    events, readable = [], []
    for bar in bars:
        for raw in bar.split():
            m = NOTE_RE.match(raw)
            if not m:
                raise ValueError(f"can't read '{raw}'")
            letter_raw, acc_raw, oct_raw, dur_raw = m.groups()
            dur_code = dur_raw or last_dur
            last_dur = dur_code.replace('.', '') if dur_raw else last_dur
            if letter_raw == '-':
                events.append({'rest': True, 'dur': dur_code})
                readable.append('rest')
                continue
            letter = letter_raw.upper()
            alter = 1 if acc_raw == '#' else (-1 if acc_raw == 'b' else 0)
            octave = int(oct_raw) if oct_raw else base_octave
            events.append({'rest': False, 'letter': letter, 'alter': alter, 'octave': octave, 'dur': dur_code})
            readable.append(to_solfa(letter, alter, octave, key_sig, base_octave))
    return events, readable


def read_musicxml(file_path, key_name, base_octave=4):
    key_sig = get_key_sig(key_name)
    tree = ET.parse(file_path)
    root = tree.getroot()
    events, readable = [], []
    for note_el in root.iter('note'):
        type_text = note_el.findtext('type', default='quarter')
        dur_code = TYPE_TO_DUR.get(type_text, '4')
        if note_el.find('dot') is not None:
            dur_code += '.'
        if note_el.find('rest') is not None:
            events.append({'rest': True, 'dur': dur_code})
            readable.append('rest')
            continue
        pitch = note_el.find('pitch')
        if pitch is None:
            continue
        step = pitch.findtext('step', default='C')
        alter = int(pitch.findtext('alter', default='0') or '0')
        octave = int(pitch.findtext('octave', default='4') or '4')
        events.append({'rest': False, 'letter': step, 'alter': alter, 'octave': octave, 'dur': dur_code})
        readable.append(to_solfa(step, alter, octave, key_sig, base_octave))
    if not readable:
        raise ValueError("no notes found in that file")
    return events, readable


# --------------------------------------------------------------- audio ---

def midi_number(letter, alter, octave):
    return 12 * (octave + 1) + LETTER_SEMI[letter] + alter


def freq_for_midi(midi):
    return 440.0 * (2.0 ** ((midi - 69) / 12.0))


def write_preview_wav(path, events, tempo_bpm=100, sample_rate=44100):
    seconds_per_quarter = 60.0 / max(tempo_bpm, 1)
    samples = []
    for ev in events:
        dur_code = ev['dur']
        quarters = QUARTER_MAP.get(dur_code.rstrip('.') or '4', 1.0) * (1.5 if dur_code.endswith('.') else 1.0)
        n_total = max(1, int(sample_rate * quarters * seconds_per_quarter))
        if ev.get('rest'):
            samples.extend([0] * n_total)
            continue
        midi = midi_number(ev['letter'], ev.get('alter', 0), ev['octave'])
        freq = freq_for_midi(midi)
        gap = max(1, int(n_total * 0.08))
        tone_len = max(1, n_total - gap)
        fade = max(1, int(sample_rate * 0.008))
        for i in range(tone_len):
            t = i / sample_rate
            env = 1.0
            if i < fade:
                env = i / fade
            elif i > tone_len - fade:
                env = max(0.0, (tone_len - i) / fade)
            val = env * 0.5 * math.sin(2 * math.pi * freq * t)
            samples.append(int(val * 32767))
        samples.extend([0] * gap)
    with wave.open(str(path), 'w') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(array.array('h', samples).tobytes())
    return path


def play_audio(path):
    path = str(path)
    try:
        if sys.platform.startswith('darwin'):
            subprocess.run(['afplay', path], check=False)
            return True
        if sys.platform.startswith('win'):
            import winsound
            winsound.PlaySound(path, winsound.SND_FILENAME)
            return True
        for cmd in ('paplay', 'aplay', 'play'):
            if shutil.which(cmd):
                subprocess.run([cmd, path], check=False)
                return True
        return False
    except Exception:
        return False


# ------------------------------------------------------------------ run ---

def run(parameters: dict, player=None, session_memory=None) -> str:
    try:
        key = (parameters.get("key") or "").strip()
        notes = (parameters.get("notes") or "").strip()
        file_path = (parameters.get("file_path") or "").strip()
        play_flag = parameters.get("play", True)
        if isinstance(play_flag, str):
            play_flag = play_flag.strip().lower() not in ("false", "no", "0")
        tempo = parameters.get("tempo") or 100
        try:
            tempo = float(tempo)
        except (TypeError, ValueError):
            tempo = 100

        if not key:
            return "Which key is this written in, sir? I need that to work out the sol-fa."
        if not notes and not file_path:
            return "I'll need either the note names or a file to read from, sir."

        songs_dir = Path.home() / "jarvis_songs"
        songs_dir.mkdir(parents=True, exist_ok=True)

        if file_path:
            src = Path(file_path).expanduser()
            if not src.exists():
                return f"I can't find a file at {src}, sir."
            events, readable = read_musicxml(src, key)
            wav_path = src.with_suffix('.wav')
        else:
            events, readable = parse_notes(notes, key)
            wav_path = songs_dir / f"preview_{time.strftime('%Y%m%d_%H%M%S')}.wav"

        write_preview_wav(wav_path, events, tempo_bpm=tempo)

        played = False
        if play_flag:
            if player:
                try:
                    player.write_log(f"JARVIS: playing preview of {wav_path}")
                except Exception:
                    pass
            played = play_audio(wav_path)

        summary = ' '.join(readable)

        if player:
            try:
                player.write_log(f"JARVIS: read staff back as sol-fa in {key} major")
            except Exception:
                pass

        base = f"In {key} major, sir, that reads: {summary}."
        if play_flag and played:
            return base + " Here's how it sounds."
        if play_flag and not played:
            return base + f" I couldn't find a way to play it aloud here, but the preview is saved at {wav_path}."
        return base
    except Exception as e:
        return f"Sir, staff_to_solfa ran into trouble: {e}"
