# test_client.py -- Tests for the git protocol, client side
# Copyright (C) 2009 Jelmer Vernooij <jelmer@samba.org>
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; version 2
# or (at your option) any later version of the License.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
# MA  02110-1301, USA.

from io import BytesIO

from dulwich.client import (
    TraditionalGitClient,
    TCPGitClient,
    SubprocessGitClient,
    SSHGitClient,
    HttpGitClient,
    ReportStatusParser,
    SendPackError,
    UpdateRefsError,
    get_transport_and_path,
    )
from dulwich.tests import (
    TestCase,
    )
from dulwich.protocol import (
    TCP_GIT_PORT,
    Protocol,
    )


class DummyClient(TraditionalGitClient):

    def __init__(self, can_read, read, write):
        self.can_read = can_read
        self.read = read
        self.write = write
        TraditionalGitClient.__init__(self)

    def _connect(self, service, path):
        return Protocol(self.read, self.write, None), self.can_read


# TODO(durin42): add unit-level tests of GitClient
class GitClientTests(TestCase):

    def setUp(self):
        super(GitClientTests, self).setUp()
        self.rout = BytesIO()
        self.rin = BytesIO()

        def _closeit():
            self.rin.close()
            self.rout.close()

        self.client = DummyClient(lambda x: True, self.rin.read,
                                  self.rout.write)
        self.addCleanup(_closeit)

    def test_caps(self):
        self.assertEqual(set([b'multi_ack', b'side-band-64k', b'ofs-delta',
                               b'thin-pack', b'multi_ack_detailed']),
                          set(self.client._fetch_capabilities))
        self.assertEqual(set([b'ofs-delta', b'report-status', b'side-band-64k']),
                          set(self.client._send_capabilities))

    def test_fetch_pack_none(self):
        self.rin.write(
            b'008855dcc6bf963f922e1ed5c4bbaaefcfacef57b1d7 HEAD.multi_ack '
            b'thin-pack side-band side-band-64k ofs-delta shallow no-progress '
            b'include-tag\n'
            b'0000')
        self.rin.seek(0)
        self.client.fetch_pack('bla', lambda heads: [], None, None, None)
        self.assertEqual(self.rout.getvalue(), b'0000')

    def test_get_transport_and_path_tcp(self):
        client, path = get_transport_and_path('git://foo.com/bar/baz')
        self.assertTrue(isinstance(client, TCPGitClient))
        self.assertEqual('foo.com', client._host)
        self.assertEqual(TCP_GIT_PORT, client._port)
        self.assertEqual('/bar/baz', path)

        client, path = get_transport_and_path('git://foo.com:1234/bar/baz')
        self.assertTrue(isinstance(client, TCPGitClient))
        self.assertEqual('foo.com', client._host)
        self.assertEqual(1234, client._port)
        self.assertEqual('/bar/baz', path)

    def test_get_transport_and_path_ssh_explicit(self):
        client, path = get_transport_and_path('git+ssh://foo.com/bar/baz')
        self.assertTrue(isinstance(client, SSHGitClient))
        self.assertEqual('foo.com', client.host)
        self.assertEqual(None, client.port)
        self.assertEqual(None, client.username)
        self.assertEqual('/bar/baz', path)

        client, path = get_transport_and_path(
            'git+ssh://foo.com:1234/bar/baz')
        self.assertTrue(isinstance(client, SSHGitClient))
        self.assertEqual('foo.com', client.host)
        self.assertEqual(1234, client.port)
        self.assertEqual('/bar/baz', path)

    def test_get_transport_and_path_ssh_implicit(self):
        client, path = get_transport_and_path('foo:/bar/baz')
        self.assertTrue(isinstance(client, SSHGitClient))
        self.assertEqual('foo', client.host)
        self.assertEqual(None, client.port)
        self.assertEqual(None, client.username)
        self.assertEqual('/bar/baz', path)

        client, path = get_transport_and_path('foo.com:/bar/baz')
        self.assertTrue(isinstance(client, SSHGitClient))
        self.assertEqual('foo.com', client.host)
        self.assertEqual(None, client.port)
        self.assertEqual(None, client.username)
        self.assertEqual('/bar/baz', path)

        client, path = get_transport_and_path('user@foo.com:/bar/baz')
        self.assertTrue(isinstance(client, SSHGitClient))
        self.assertEqual('foo.com', client.host)
        self.assertEqual(None, client.port)
        self.assertEqual('user', client.username)
        self.assertEqual('/bar/baz', path)

    def test_get_transport_and_path_subprocess(self):
        client, path = get_transport_and_path('foo.bar/baz')
        self.assertTrue(isinstance(client, SubprocessGitClient))
        self.assertEqual('foo.bar/baz', path)

    def test_get_transport_and_path_error(self):
        # Need to use a known urlparse.uses_netloc URL scheme to get the
        # expected parsing of the URL on Python versions less than 2.6.5
        self.assertRaises(ValueError, get_transport_and_path,
        'prospero://bar/baz')

    def test_get_transport_and_path_http(self):
        url = 'https://github.com/jelmer/dulwich'
        client, path = get_transport_and_path(url)
        self.assertTrue(isinstance(client, HttpGitClient))
        self.assertEqual('/jelmer/dulwich', path)


class SSHGitClientTests(TestCase):

    def setUp(self):
        super(SSHGitClientTests, self).setUp()
        self.client = SSHGitClient('git.samba.org')

    def test_default_command(self):
        self.assertEqual('git-upload-pack',
                self.client._get_cmd_path('upload-pack'))

    def test_alternative_command_path(self):
        self.client.alternative_paths['upload-pack'] = (
            '/usr/lib/git/git-upload-pack')
        self.assertEqual('/usr/lib/git/git-upload-pack',
            self.client._get_cmd_path('upload-pack'))


class ReportStatusParserTests(TestCase):

    def test_invalid_pack(self):
        parser = ReportStatusParser()
        parser.handle_packet(b"unpack error - foo bar")
        parser.handle_packet(b"ok refs/foo/bar")
        parser.handle_packet(None)
        self.assertRaises(SendPackError, parser.check)

    def test_update_refs_error(self):
        parser = ReportStatusParser()
        parser.handle_packet(b"unpack ok")
        parser.handle_packet(b"ng refs/foo/bar need to pull")
        parser.handle_packet(None)
        self.assertRaises(UpdateRefsError, parser.check)

    def test_ok(self):
        parser = ReportStatusParser()
        parser.handle_packet(b"unpack ok")
        parser.handle_packet(b"ok refs/foo/bar")
        parser.handle_packet(None)
        parser.check()
