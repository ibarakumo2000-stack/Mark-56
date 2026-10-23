"""
JARVIS plugin: solfa_to_staff

Takes tonic sol-fa notation (d r m f s l t ...) plus a key and time signature,
works out the correctly-spelled notes for that key, writes a standard
.musicxml file to ~/jarvis_songs/ that any notation program (MuseScore,
Finale, Sibelius, flat.io, etc.) can open, and plays a short synthesized
audio preview of the melody so the user can hear it back immediately.

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
from xml.sax.saxutils import escape

PLUGIN = {
    "name": "solfa_to_staff",
    "description": (
        "Transcribes tonic sol-fa notation (d r m f s l t, e.g. 'd4 r4 m4 f4 | s2') "
        "into written staff notation, saves it as a .musicxml file the user can open "
        "in notation software, and plays a short audio preview of the melody. Use "
        "this when the user dictates or types a melody in sol-fa and wants it written "
        "out as staff / sheet music, or wants to hear it played back. Requires a key "
        "(e.g. C, G, D, F, Bb) and a time signature (e.g. 4/4) — if either is missing, "
        "ask the user for it rather than guessing, then call this tool again. "
        "Do NOT use this tool to read or interpret existing notes/staff notation back "
        "into sol-fa — use staff_to_solfa for that instead."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "solfa": {
                "type": "STRING",
                "description": (
                    "The sol-fa melody. Degrees d r m f s l t; d' = octave up, d, = "
                    "octave down; chromatics di ri fi si li (raised) / ra me se le te "
                    "(lowered); a trailing # or b also raises/lowers a step. Duration "
                    "follows the note as a digit (4 quarter, 8 eighth, 2 half, 1 whole, "
                    "16 sixteenth; add . to dot it) and carries over if omitted. Rest "
                    "is '-'. Bars are separated by '|'. Example: 'd4 r4 m4 f4 | s2 -2'."
                ),
            },
            "key": {
                "type": "STRING",
                "description": "The major key to write in, e.g. C, G, D, A, E, B, F#, F, Bb, Eb, Ab, Db.",
            },
            "time_signature": {
                "type": "STRING",
                "description": "Time signature as beats/beat-value, e.g. '4/4', '3/4', '6/8'.",
            },
            "title": {
                "type": "STRING",
                "description": "Optional title for the piece, also used as the saved file name.",
            },
            "play": {
                "type": "BOOLEAN",
                "description": "Whether to play an audio preview after writing it. Defaults to true.",
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

SYLLABLES = {
    'd': (0, 0), 'ra': (1, -1), 'r': (1, 0), 'me': (2, -1), 'm': (2, 0),
    'f': (3, 0), 'fi': (3, 1), 's': (4, 0), 'se': (4, -1), 'si': (4, 1),
    'l': (5, 0), 'le': (5, -1), 'li': (5, 1), 't': (6, 0), 'te': (6, -1),
    'di': (0, 1), 'ri': (1, 1),
}

TOKEN_RE = re.compile(
    r"^(di|ri|fi|si|li|ra|me|se|le|te|[dmrfslt]|-)([',]*)([#b]?)(\d*)(\.*)$",
    re.IGNORECASE,
)

# duration code -> (divisions-of-a-quarter units, musicxml type name)
DUR_MAP = {
    '1': (16, 'whole'), '2': (8, 'half'), '4': (4, 'quarter'),
    '8': (2, 'eighth'), '16': (1, '16th'), '32': (0.5, '32nd'),
}
# duration code -> length in quarter notes, for audio timing
QUARTER_MAP = {'1': 4.0, '2': 2.0, '4': 1.0, '8': 0.5, '16': 0.25, '32': 0.125}


def get_key_sig(key_name):
    key_name = key_name.strip()
    key_name = key_name[0].upper() + key_name[1:] if key_name else key_name
    tonic_letter = key_name[0].upper() if key_name else 'C'
    if key_name in SHARP_KEYS:
        n = SHARP_KEYS[key_name]
        return {'tonic_letter': tonic_letter, 'type': 'sharp', 'altered': SHARP_ORDER[:n], 'fifths': n}
    if key_name in FLAT_KEYS:
        n = FLAT_KEYS[key_name]
        return {'tonic_letter': tonic_letter, 'type': 'flat', 'altered': FLAT_ORDER[:n], 'fifths': -n}
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
    wraps = (tonic_idx + total_degree) // 7  # floor division: correct for negatives
    octave = base_octave + wraps
    return letter, key_sig_acc(key_sig, letter), octave


def parse_solfa(text, key_name, base_octave=4):
    key_sig = get_key_sig(key_name)
    bars = [b.strip() for b in text.strip().split('|') if b.strip()]
    if not bars:
        raise ValueError("no sol-fa notes found")
    last_dur = '4'
    measures, readable = [], []
    for bar in bars:
        notes = []
        for raw in bar.split():
            m = TOKEN_RE.match(raw.lower())
            if not m:
                raise ValueError(f"can't read '{raw}'")
            syl, marks, suf, dur_digits, dots = m.groups()
            dur_code = (dur_digits or last_dur) + dots
            last_dur = dur_digits or last_dur
            if syl == '-':
                notes.append({'rest': True, 'dur': dur_code})
                readable.append(f"rest({dur_code})")
                continue
            deg, chroma_acc = SYLLABLES[syl]
            octave_shift = 7 * (marks.count("'") - marks.count(','))
            letter, _key_acc, octave = note_for_degree(key_sig, base_octave, deg + octave_shift)
            suf_acc = 1 if suf == '#' else (-1 if suf == 'b' else 0)
            alter = chroma_acc + suf_acc
            notes.append({'rest': False, 'letter': letter, 'alter': alter, 'octave': octave, 'dur': dur_code})
            sym = {0: '', 1: '#', -1: 'b', 2: '##', -2: 'bb'}.get(alter, '')
            readable.append(f"{letter}{sym}{octave}({dur_code})")
        measures.append(notes)
    return measures, readable, key_sig


# ------------------------------------------------------------ musicxml ---

def dur_to_xml(dur_code):
    dotted = dur_code.endswith('.')
    base = dur_code.rstrip('.') or '4'
    units, type_name = DUR_MAP.get(base, DUR_MAP['4'])
    if dotted:
        units *= 1.5
    return units, type_name, dotted


def build_musicxml(measures, key_sig, time_signature, title):
    beats, beat_type = (time_signature.split('/') + ['4', '4'])[:2]
    try:
        beats, beat_type = int(beats), int(beat_type)
    except ValueError:
        beats, beat_type = 4, 4

    parts = []
    parts.append('<?xml version="1.0" encoding="UTF-8"?>')
    parts.append(
        '<!DOCTYPE score-partwise PUBLIC "-//Recordare//DTD MusicXML 3.1 Partwise//EN" '
        '"http://www.musicxml.org/dtds/partwise.dtd">'
    )
    parts.append('<score-partwise version="3.1">')
    parts.append(f'  <work><work-title>{escape(title)}</work-title></work>')
    parts.append('  <part-list><score-part id="P1"><part-name>Sol-fa</part-name></score-part></part-list>')
    parts.append('  <part id="P1">')

    for i, measure in enumerate(measures, start=1):
        parts.append(f'    <measure number="{i}">')
        if i == 1:
            parts.append('      <attributes>')
            parts.append('        <divisions>4</divisions>')
            parts.append(f'        <key><fifths>{key_sig["fifths"]}</fifths></key>')
            parts.append(f'        <time><beats>{beats}</beats><beat-type>{beat_type}</beat-type></time>')
            parts.append('        <clef><sign>G</sign><line>2</line></clef>')
            parts.append('      </attributes>')
        for note in measure:
            units, type_name, dotted = dur_to_xml(note['dur'])
            parts.append('      <note>')
            if note['rest']:
                parts.append('        <rest/>')
            else:
                parts.append('        <pitch>')
                parts.append(f'          <step>{note["letter"]}</step>')
                if note['alter']:
                    parts.append(f'          <alter>{note["alter"]}</alter>')
                parts.append(f'          <octave>{note["octave"]}</octave>')
                parts.append('        </pitch>')
            parts.append(f'        <duration>{units}</duration>')
            parts.append(f'        <type>{type_name}</type>')
            if dotted:
                parts.append('        <dot/>')
            parts.append('      </note>')
        parts.append('    </measure>')

    parts.append('  </part>')
    parts.append('</score-partwise>')
    return '\n'.join(parts)


# --------------------------------------------------------------- audio ---

def midi_number(letter, alter, octave):
    return 12 * (octave + 1) + LETTER_SEMI[letter] + alter


def freq_for_midi(midi):
    return 440.0 * (2.0 ** ((midi - 69) / 12.0))


def write_preview_wav(path, events, tempo_bpm=100, sample_rate=44100):
    seconds_per_quarter = 60.0 / max(tempo_bpm, 1)
    samples = []
    for ev in events:
        quarters = QUARTER_MAP.get(ev['dur'].rstrip('.') or '4', 1.0) * (1.5 if ev['dur'].endswith('.') else 1.0)
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
        solfa = (parameters.get("solfa") or "").strip()
        key = (parameters.get("key") or "").strip()
        time_signature = (parameters.get("time_signature") or "").strip()
        title = (parameters.get("title") or "").strip() or "Untitled"
        play_flag = parameters.get("play", True)
        if isinstance(play_flag, str):
            play_flag = play_flag.strip().lower() not in ("false", "no", "0")
        tempo = parameters.get("tempo") or 100
        try:
            tempo = float(tempo)
        except (TypeError, ValueError):
            tempo = 100

        if not solfa:
            return "I'll need the sol-fa itself before I can write anything down, sir."
        if not key:
            return "Certainly, sir — which key shall I write this in? C, G, D, F and B flat are all fine."
        if not time_signature:
            return "And the time signature, sir? Four-four is standard, unless you'd like something else."

        measures, readable, key_sig = parse_solfa(solfa, key)
        xml = build_musicxml(measures, key_sig, time_signature, title)

        songs_dir = Path.home() / "jarvis_songs"
        songs_dir.mkdir(parents=True, exist_ok=True)
        fname = re.sub(r'[^a-zA-Z0-9_-]+', '_', title.lower()).strip('_') or 'song'
        xml_path = songs_dir / f"{fname}.musicxml"
        xml_path.write_text(xml, encoding='utf-8')

        events = [n for measure in measures for n in measure]
        wav_path = songs_dir / f"{fname}.wav"
        write_preview_wav(wav_path, events, tempo_bpm=tempo)

        played = False
        if play_flag:
            if player:
                try:
                    player.write_log(f"JARVIS: playing preview of {wav_path}")
                except Exception:
                    pass
            played = play_audio(wav_path)

        if player:
            try:
                player.write_log(f"JARVIS: wrote staff notation to {xml_path}")
            except Exception:
                pass

        note_summary = " ".join(readable)
        base = (
            f'Done, sir. "{title}" is written in {key} major, {time_signature} time, '
            f'and saved to {xml_path}. The notes run: {note_summary}.'
        )
        if play_flag and played:
            return base + " Here's how it sounds."
        if play_flag and not played:
            return base + f" I couldn't find a way to play it aloud here, but the preview is saved at {wav_path}."
        return base
    except Exception as e:
        return f"Sir, solfa_to_staff ran into trouble: {e}"
