"""Tests for server.lib.constants."""

from server.lib.constants import DEFAULT_SERVER_PORTS


class TestDefaultServerPorts:
    def test_all_expected_servers_present(self):
        expected = {"hooks", "sandbox", "proj", "worktree", "trello", "jira", "todoist"}
        assert expected == set(DEFAULT_SERVER_PORTS.keys())

    def test_no_duplicate_ports(self):
        ports = list(DEFAULT_SERVER_PORTS.values())
        assert len(ports) == len(set(ports))

    def test_ports_in_valid_range(self):
        for port in DEFAULT_SERVER_PORTS.values():
            assert 1024 <= port <= 65535
