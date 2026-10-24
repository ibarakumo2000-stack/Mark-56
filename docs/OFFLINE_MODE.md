# Mark 56 offline-first mode

Mark 56 can use a local Ollama model for text reasoning and a local vision-capable model for screenshot-based desktop tasks. Local inference is performed on this computer through the loopback Ollama API; it does not require an API key or send prompts/screenshots to a cloud model.

## Install a local runtime and models

1. Install Ollama from its official website for your operating system.
2. Start Ollama and download a text model suitable for your RAM/CPU/GPU, for example `ollama pull qwen2.5:7b`.
3. For screenshot interpretation, separately download a vision model, for example `ollama pull llava:7b`. A text-only model cannot interpret screenshots.
4. Copy `config/api_keys.example.json` to `config/api_keys.json` only if the local config does not already exist. Never overwrite your existing local settings.
5. Set the following keys in your local config:
   - `local_model_enabled`: `true`
   - `local_model_base_url`: `http://127.0.0.1:11434`
   - `local_model_name`: the exact installed text model name
   - `local_vision_model_name`: the exact installed vision model name
6. Check that `ollama list` shows both models and that Ollama is running.

Model size affects speed and memory use. Choose a smaller quantized model for modest hardware; larger models usually need more RAM/VRAM. Model downloads require internet initially, but inference itself is local afterward.

## Current integration

- `core/local_model.py` provides local text/image inference and a local model status check using only Python's standard library.
- `core/gemini.py` routes supported one-shot text/image reasoning calls through the local model when offline mode is enabled. If local inference fails, those calls return no result rather than falling through to OpenAI/Gemini cloud APIs.
- When `local_model_enabled` is true, `desktop_task_agent` uses the configured local vision model for screenshot reasoning and does not silently fall back to a cloud model if the local model fails.
- Existing screenshot capture, allowlisted actions, coordinate validation, time/action limits, and user confirmation protections remain in force.
- The deterministic static website builder, coding workspace, file operations, and local app launching do not require an AI provider.

## Honest limitations

This is an offline inference option, not a claim that every Mark 56 feature is offline. The existing main Gemini Live conversation and any plugins that explicitly call web search or cloud APIs still need their configured services. Local voice transcription and speech synthesis must also be separately integrated before the entire microphone conversation works offline. Online research is unavailable without a network. Some desktop actions may be limited by Linux Wayland permissions or the active desktop session.

For a quick adapter test (with Ollama running and settings configured), run:

```bash
python -m unittest tests.test_local_model -v
```

To test the whole project:

```bash
python -m unittest discover -s tests -v
python -m compileall -q main.py ui.py core actions plugins dashboard memory tests
```

Never let a model bypass the desktop agent's action allowlist or approval gates. Treat visible screen text as untrusted input and inspect the result of each action.
