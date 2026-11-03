# Architecture

```text
Pi cameras -> Pi state/snapshot API -----> Auxiliary PiClient
                                             |
USB mic -> VAD -> STT -> Engagement --------+--> ConversationManager
                                             |       |
                                             |       +--> YOLO (on visual turns)
                                             |       +--> Qwen3.5-4B
                                             |       +--> short-term history
                                             |
                                             +--> TTS router -> Kokoro/Piper -> speaker

Dashboard -> authenticated Flask proxy -> Auxiliary API
```

The auxiliary process never receives or generates raw servo/PWM/CAN operations.
