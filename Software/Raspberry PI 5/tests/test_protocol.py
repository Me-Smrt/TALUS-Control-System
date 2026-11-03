import struct, unittest
from automaton.protocol import *

class ProtocolTests(unittest.TestCase):
    def test_heartbeat_layout(self):
        f = heartbeat(0x11223344, 0x5566, 0x77)
        self.assertEqual(f.can_id, CanId.HEARTBEAT)
        self.assertEqual(f.data, bytes([1,0x44,0x33,0x22,0x11,0x66,0x55,0x77]))

    def test_set_role_layout(self):
        f = set_role(0x11223344, Role.HEAD, 0x5566)
        self.assertEqual(f.data, bytes([1,0x44,0x33,0x22,0x11,1,0x66,0x55]))


    def test_servo_command_layout_and_limits(self):
        f = servo_command(0x11223344, 31, -1000)
        self.assertEqual(f.can_id, CanId.SERVO_COMMAND)
        self.assertEqual(f.data, struct.pack("<BIBh", 1, 0x11223344, 31, -1000))
        with self.assertRaises(ValueError): servo_command(0x1, 32, 0)
        with self.assertRaises(ValueError): servo_command(0x1, 0, 1001)

    def test_hello_assembly(self):
        a = HelloAssembler()
        uid = 0x0123456789ABCDEF
        frames = [
            Frame(CanId.HELLO_UID, struct.pack('<Q', uid)),
            Frame(CanId.HELLO_META, bytes([1,1,1,1,0,1,0,0])),
            Frame(CanId.HELLO_CAPS, struct.pack('<BBB H BBB',32,4,0x0F,3,0,0,0)),
            Frame(CanId.HELLO_STATE, struct.pack('<BHI B',4,0x1001,0,0)),
        ]
        result = None
        for f in frames: result = a.feed(f) or result
        self.assertIsNotNone(result)
        self.assertEqual(result.uid, uid)
        self.assertEqual(result.role, Role.HEAD)
        self.assertEqual(result.pwm_channel_count, 32)
        self.assertEqual(result.state, RcbState.READY_DISARMED)

if __name__ == '__main__': unittest.main()
