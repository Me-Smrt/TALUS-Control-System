import tempfile, unittest
from pathlib import Path
from automaton.protocol import Role
from automaton.registry import RcbRegistry, RegistryConflict

class RegistryTests(unittest.TestCase):
    def test_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)/'registry.json'
            r = RcbRegistry(p); r.assign(Role.HEAD, 0xAA, 'can7', channel=2); r.save()
            r2 = RcbRegistry(p); r2.load()
            self.assertEqual(r2.nodes['HEAD'].uid, '00000000000000AA')
            self.assertEqual(r2.nodes['HEAD'].channel, 2)
            self.assertEqual(r2.nodes['HEAD'].interface, 'can7')

    def test_refuses_silent_role_remap(self):
        r = RcbRegistry(Path('/tmp/unused.json'))
        r.assign(Role.HEAD, 0xAA, 'can2', channel=2)
        with self.assertRaises(RegistryConflict): r.assign(Role.HEAD, 0xBB, 'can3', channel=3)

    def test_refuses_same_uid_two_roles(self):
        r = RcbRegistry(Path('/tmp/unused.json'))
        r.assign(Role.HEAD, 0xAA, 'can2', channel=2)
        with self.assertRaises(RegistryConflict): r.assign(Role.LEFT_ARM, 0xAA, 'can4', channel=4)

    def test_linux_interface_rename_is_not_identity_change(self):
        r = RcbRegistry(Path('/tmp/unused.json'))
        r.assign(Role.HEAD, 0xAA, 'can2', channel=2)
        self.assertEqual(r.validate_observation(Role.HEAD, 0xAA, 'can6', channel=2), [])
        r.update_observed_interface(Role.HEAD, 0xAA, 'can6', channel=2)
        self.assertEqual(r.nodes['HEAD'].interface, 'can6')

    def test_physical_socket_move_is_blocked(self):
        r = RcbRegistry(Path('/tmp/unused.json'))
        r.assign(Role.HEAD, 0xAA, 'can2', channel=2)
        problems = r.validate_observation(Role.HEAD, 0xAA, 'can4', channel=4)
        self.assertTrue(any('physical CCB channel 2' in p for p in problems))

    def test_old_registry_without_channel_remains_loadable(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)/'registry.json'
            p.write_text('{"protocol_version":1,"nodes":{"HEAD":{"uid":"00000000000000AA","interface":"can2","expected_hardware":"RCB-R1","enabled":true}}}')
            r = RcbRegistry(p); r.load()
            self.assertIsNone(r.nodes['HEAD'].channel)

if __name__ == '__main__': unittest.main()
