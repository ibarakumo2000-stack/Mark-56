# Optional voice and model providers

This folder contains the optional STT → LLM → TTS engine adapted from
[FatihMakes/Mark-LVII](https://github.com/FatihMakes/Mark-LVII), licensed under
the same Creative Commons Attribution-NonCommercial 4.0 terms already used by
this repository. Mark 56's existing Gemini Live session remains the default.

## Available provider families

- OpenAI-compatible LLM endpoints: Ollama, LM Studio, llama.cpp, vLLM and hosted compatible APIs.
- Whisper speech recognition: local CPU mode or compatible transcription APIs.
- System TTS, Piper neural TTS, and ElevenLabs TTS.

The provider modules are imported only after the user opens Engine & Providers
or selects the pipeline engine. Gemini Live remains unchanged for existing
installations and no optional speech model is downloaded automatically.

## Local setup

For the existing Ollama service, configure the OpenAI-compatible address as
`http://127.0.0.1:11434/v1` and select the model installed in Ollama.

Optional extras, installed only when the corresponding provider is selected:

- `pip install faster-whisper` for local Whisper STT.
- `pip install piper-tts` for local Piper speech.

Use System Voice if Piper is not installed. Hosted STT / LLM / TTS providers
send the relevant audio or text to their service; local providers keep that
processing on this computer.
