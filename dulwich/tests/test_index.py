# test_index.py -- Tests for the git index
# Copyright (C) 2008-2009 Jelmer Vernooij <jelmer@samba.org>
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

"""Tests for the index."""


from io import (
    BytesIO,
    )
import os
import shutil
import stat
import struct
import tempfile

from dulwich.index import (
    Index,
    cleanup_mode,
    commit_tree,
    read_index,
    write_cache_time,
    write_index,
    )
from dulwich.object_store import (
    MemoryObjectStore,
    )
from dulwich.objects import (
    Blob,
    )
from dulwich.sha1 import Sha1Sum
from dulwich.tests import TestCase


class IndexTestCase(TestCase):

    datadir = os.path.join(os.path.dirname(__file__), 'data/indexes')

    def get_simple_index(self, name):
        return Index(os.path.join(self.datadir, name))


class SimpleIndexTestCase(IndexTestCase):

    def test_len(self):
        self.assertEqual(1, len(self.get_simple_index("index")))

    def test_iter(self):
        self.assertEqual(['bla'], list(self.get_simple_index("index")))

    def test_getitem(self):
        self.assertEqual(((1230680220, 0), (1230680220, 0), 2050, 3761020,
                           33188, 1000, 1000, 0,
                           'e69de29bb2d1d6434b8b29ae775ad8c2e48c5391', 0),
                          self.get_simple_index("index")["bla"])

    def test_empty(self):
        i = self.get_simple_index("notanindex")
        self.assertEqual(0, len(i))
        self.assertFalse(os.path.exists(i._filename))


class SimpleIndexWriterTestCase(IndexTestCase):

    def setUp(self):
        IndexTestCase.setUp(self)
        self.tempdir = tempfile.mkdtemp()

    def tearDown(self):
        IndexTestCase.tearDown(self)
        shutil.rmtree(self.tempdir)

    def test_simple_write(self):
        entries = [(b'barbla', (1230680220, 0), (1230680220, 0), 2050, 3761020,
                    33188, 1000, 1000, 0,
                    Sha1Sum('e69de29bb2d1d6434b8b29ae775ad8c2e48c5391'), 0)]
        filename = os.path.join(self.tempdir, 'test-simple-write-index')
        with open(filename, 'wb+') as x:
            write_index(x, entries)
        with open(filename, 'rb') as x:
            self.assertEqual(entries, list(read_index(x)))


class CommitTreeTests(TestCase):

    def setUp(self):
        super(CommitTreeTests, self).setUp()
        self.store = MemoryObjectStore()

    def test_single_blob(self):
        blob = Blob()
        blob.data = "foo"
        self.store.add_object(blob)
        blobs = [("bla", blob.id, stat.S_IFREG)]
        rootid = commit_tree(self.store, blobs)
        self.assertEqual(rootid, b"1a1e80437220f9312e855c37ac4398b68e5c1d50")
        self.assertEqual((stat.S_IFREG, blob.id), self.store[rootid]["bla"])
        self.assertEqual(set([rootid, blob.id]), set(self.store._data.keys()))

    def test_nested(self):
        blob = Blob()
        blob.data = b"foo"
        self.store.add_object(blob)
        blobs = [(b"bla/bar", blob.id, stat.S_IFREG)]
        rootid = commit_tree(self.store, blobs)
        self.assertEqual(rootid, b"d92b959b216ad0d044671981196781b3258fa537")
        dirid = self.store[rootid]["bla"][1]
        self.assertEqual(dirid, b"c1a1deb9788150829579a8b4efa6311e7b638650")
        self.assertEqual((stat.S_IFDIR, dirid), self.store[rootid]["bla"])
        self.assertEqual((stat.S_IFREG, blob.id), self.store[dirid]["bar"])
        self.assertEqual(set([rootid, dirid, blob.id]),
                          set(self.store._data.keys()))


class CleanupModeTests(TestCase):

    def test_file(self):
        self.assertEqual(0o100644, cleanup_mode(0o100000))

    def test_executable(self):
        self.assertEqual(0o100755, cleanup_mode(0o100711))

    def test_symlink(self):
        self.assertEqual(0o120000, cleanup_mode(0o120711))

    def test_dir(self):
        self.assertEqual(0o40000, cleanup_mode(0o40531))

    def test_submodule(self):
        self.assertEqual(0o160000, cleanup_mode(0o160744))


class WriteCacheTimeTests(TestCase):

    def test_write_string(self):
        f = BytesIO()
        self.assertRaises(TypeError, write_cache_time, f, "foo")

    def test_write_int(self):
        f = BytesIO()
        write_cache_time(f, 434343)
        self.assertEqual(struct.pack(">LL", 434343, 0), f.getvalue())

    def test_write_tuple(self):
        f = BytesIO()
        write_cache_time(f, (434343, 21))
        self.assertEqual(struct.pack(">LL", 434343, 21), f.getvalue())

    def test_write_float(self):
        f = BytesIO()
        write_cache_time(f, 434343.000000021)
        self.assertEqual(struct.pack(">LL", 434343, 21), f.getvalue())
