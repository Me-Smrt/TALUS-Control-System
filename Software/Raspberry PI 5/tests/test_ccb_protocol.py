from automaton.ccb_protocol import *


def test_ccb_frame_round_trip():
    original = Frame(MessageType.SET_CAN_ENABLE, 0x1234, channel_payload(0xAABBCCDD, 7, True))
    assert decode(encode(original)) == original


def test_crc_rejects_corruption():
    raw = bytearray(encode(Frame(MessageType.STATUS_REQUEST, 1, b"")))
    raw[12] ^= 0x40
    try:
        decode(bytes(raw))
    except ValueError as exc:
        assert "CRC" in str(exc)
    else:
        raise AssertionError("corrupt frame accepted")


def test_status_parse():
    payload = bytearray(20)
    payload[0] = SupervisorState.RUN_DISARMED
    payload[1:3] = int(StatusBits.ESTOP_HEALTHY | StatusBits.SESSION_VALID).to_bytes(2, "little")
    payload[3:7] = int(FaultBits.NONE).to_bytes(4, "little")
    payload[7] = 0x03
    payload[8] = 0x01
    payload[9] = 0xFF
    payload[10] = 0
    payload[11] = 0xFF
    payload[12:16] = (0x11223344).to_bytes(4, "little")
    payload[16:18] = (50).to_bytes(2, "little")
    payload[18:20] = (60).to_bytes(2, "little")
    status = parse_status(Frame(MessageType.STATUS, 2, bytes(payload)))
    assert status.state == SupervisorState.RUN_DISARMED
    assert status.session_id == 0x11223344
    assert status.can_enable_mask == 0xFF
    assert status.service_channel is None


def test_stream_decoder_recovers_from_noise_and_bad_frame():
    decoder = FrameStreamDecoder()
    good1 = encode(Frame(MessageType.HELLO, 1, bytes(range(9))))
    bad = bytearray(encode(Frame(MessageType.STATUS_REQUEST, 2, b"")))
    bad[10] ^= 0x01
    good2 = encode(Frame(MessageType.STATUS_REQUEST, 3, b""))
    stream = b"noise" + good1 + bytes(bad) + b"junk" + good2

    out = []
    # Split at awkward positions to exercise partial-magic and partial-frame handling.
    for cut in (1, 7, 19, 31, 44, len(stream)):
        if not stream:
            break
    out.extend(decoder.feed(stream[:13]))
    out.extend(decoder.feed(stream[13:57]))
    out.extend(decoder.feed(stream[57:]))
    assert [f.seq for f in out] == [1, 3]
