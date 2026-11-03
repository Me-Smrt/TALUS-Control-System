# Local person identity and bounded personal memory

Stage-one person handling has two layers:

1. **Presence/session continuity** uses the Raspberry Pi's existing MediaPipe face state. This requires no additional face-recognition model. If the primary face leaves the camera for longer than the configured grace period, the active conversation history is cleared.
2. **Persistent identity** is optional. The auxiliary processor can use OpenCV YuNet + SFace on an on-demand Pi JPEG to map a visible face to a locally enrolled person.

The camera still belongs to the Raspberry Pi. The auxiliary processor never opens the webcam directly.

## Models

Place these files in `models/face/`:

- `face_detection_yunet_2023mar.onnx`
- `face_recognition_sface_2021dec.onnx`

With the Hugging Face CLI:

```powershell
mkdir models\face -ErrorAction SilentlyContinue
hf download opencv/face_detection_yunet face_detection_yunet_2023mar.onnx --local-dir models/face
hf download opencv/face_recognition_sface face_recognition_sface_2021dec.onnx --local-dir models/face
```

No additional Python package is required beyond the project's existing OpenCV dependency. The backend uses `cv2.FaceDetectorYN` and `cv2.FaceRecognizerSF`.

## Enrollment and console commands

Run the Pi CV service and the auxiliary console, stand clearly in front of the tracking camera, then:

```text
/enroll Taylor
```

The enrollment takes several current Pi snapshots, averages their normalized embeddings, and stores only the resulting embedding. Raw enrollment images are not retained.

Useful commands:

```text
/who
/remember I prefer concise technical explanations.
/forget-person
```

Natural explicit memory is also supported for a recognized person, for example:

```text
Remember that my robotics project uses a Raspberry Pi 5 as the control computer.
```

The system does **not** persist full arbitrary conversation automatically. Explicit `remember ...` facts are stored as bounded memories, and one separate **lossy rolling topic note** is maintained for the recognized person. The topic note is overwritten after each successful turn and is used only after direct conversation history has been cleared, so TALUS can say that it remembers the general subject without claiming to remember the exact exchange.

## Database limits

`runtime/people.sqlite3` is separate from the Tennessee Tech institutional knowledge database.

Defaults:

- maximum enrolled people: 50
- maximum explicit memories per person: 12
- maximum memory length: 400 characters
- one rolling last-topic note per person: 360 characters by default (does not consume an explicit-memory slot)
- people are evicted least-recently-seen first when the cap is exceeded
- raw face images are not stored

These values are configurable under `people` in `config/default.json`.

## Conversation reset behavior

The primary tracked face disappearing for more than `leave_grace_s` (default 2.5 seconds) clears conversation context. A short grace period avoids resetting because of one dropped detection or a brief head turn.

A confirmed change from one enrolled identity to another also clears context before the new person's remembered details are supplied to the LLM.

The current Pi perception pipeline is single-primary-person oriented. Multi-person speaker attribution can be added later by combining a multi-face tracker with microphone direction/voice activity.

## Privacy/design boundary

Face recognition is opt-in: a person is not persisted until explicitly enrolled. Personal memories remain local, bounded, and separable from the public Tennessee Tech knowledge corpus. For any eventual public deployment, review the deployment site's biometric/privacy and consent requirements before enabling enrollment broadly.

## Natural identity onboarding (v0.3.6)

Slash commands are diagnostic overrides, not the intended deployed interaction path.
For each visible conversational turn TALUS now does a cheap identity check before the
LLM is called:

1. If the face matches a stored person, their bounded context is used normally.
2. If a face is visible but unknown, TALUS is instructed to naturally ask what the
   person would like to be called (answering any substantive question first).
3. A reply such as `Taylor`, `My name is Taylor`, `I'm Taylor`, or `Call me Taylor`
   becomes a temporary session name.
4. When the local SFace backend is available, TALUS then asks whether the person
   wants to be remembered for future visits.
5. An affirmative reply performs local enrollment automatically. `Remember me as
   Taylor` is treated as direct consent and can enroll without `/enroll`.
6. A declined enrollment keeps the name only for the current visible session and
   TALUS does not repeatedly pressure the person to opt in.

Before asking an unknown person their name, the manager performs an immediate face
recognition pass so a known person is not asked simply because the background
recognition poll had not run yet. If the model ignores the name-prompt instruction,
the prompt becomes eligible again after a small configurable number of turns.

The relevant settings are:

```json
"people": {
  "onboarding_enabled": true,
  "ask_name_after_turns": 0,
  "ask_name_retry_turns": 2,
  "offer_persistent_identity": true
}
```

Temporary session names are cleared with the same person-leaves-frame lifecycle as
ordinary conversation state.

## Automatic conversational actions

The auxiliary process also has a deterministic action router in front of Qwen. It
can request a Pi-owned camera frame for normal utterances such as `What am I
holding?`, `Describe the room around you`, `Read this sign`, or `What color is
this?`. `/vision` remains useful for debugging but is no longer required for these
common visual intents.

The router is deliberately narrow: ordinary small talk or a statement such as `I
have homework due tomorrow` does not activate the camera. Future robot actions can
be added to the same pre-LLM routing layer without granting the language model raw
actuator authority.
