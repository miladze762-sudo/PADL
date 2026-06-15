import socket
import unittest

from padlbot.single_instance import SingleInstanceError, acquire_single_instance_lock


class SingleInstanceTests(unittest.TestCase):
    def test_lock_prevents_second_instance_on_same_port(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]

        first = acquire_single_instance_lock("127.0.0.1", port)
        self.addCleanup(first.close)

        with self.assertRaises(SingleInstanceError):
            acquire_single_instance_lock("127.0.0.1", port)


if __name__ == "__main__":
    unittest.main()
