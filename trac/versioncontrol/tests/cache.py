# -*- coding: utf-8 -*-
#
# Copyright (C)2005-2009 Edgewall Software
# Copyright (C) 2005 Christopher Lenz <cmlenz@gmx.de>
# All rights reserved.
#
# This software is licensed as described in the file COPYING, which
# you should have received as part of this distribution. The terms
# are also available at http://trac.edgewall.org/wiki/TracLicense.
#
# This software consists of voluntary contributions made by many
# individuals. For the exact contribution history, see the revision
# history and logs, available at http://trac.edgewall.org/log/.
#
# Author: Christopher Lenz <cmlenz@gmx.de>

from datetime import datetime

from trac.test import EnvironmentStub, Mock
from trac.util.datefmt import to_utimestamp, utc
from trac.versioncontrol import Repository, Changeset, Node, NoSuchChangeset
from trac.versioncontrol.cache import CachedRepository

import unittest


class CacheTestCase(unittest.TestCase):

    def setUp(self):
        self.env = EnvironmentStub()
        self.db = self.env.get_db_cnx()
        self.log = self.env.log
        cursor = self.db.cursor()
        cursor.executemany("""
            INSERT INTO repository (id,name,value) VALUES (%s,%s,%s)
            """, [(1, 'name', 'test-repos'),
                  (1, 'youngest_rev', '')])

    def tearDown(self):
        self.env.reset_db()

    # Helpers

    def get_repos(self, get_changeset=None, youngest_rev=1):
        if get_changeset is None:
            def no_changeset(rev):
                raise NoSuchChangeset(rev)
            get_changeset = no_changeset
        return Mock(Repository, 'test-repos', {'name': 'test-repos', 'id': 1},
                    self.log,
                    get_changeset=get_changeset,
                    get_oldest_rev=lambda: 0,
                    get_youngest_rev=lambda: youngest_rev,
                    normalize_rev=lambda x: get_changeset(x).rev,
                    next_rev=(lambda x: int(x) < youngest_rev and x + 1 \
                              or None))

    def preset_cache(self, *args):
        """Each arg is a (rev tuple, changes list of tuples) pair."""
        cursor = self.db.cursor()
        for rev, changes in args:
            cursor.execute("""
                INSERT INTO revision (repos,rev,time,author,message)
                VALUES (1,%s,%s,%s,%s)
                """, rev)
            if changes:
                cursor.executemany("""
                    INSERT INTO node_change
                    (repos,rev,path,node_type,change_type,base_path,base_rev)
                    VALUES (1,%s,%s,%s,%s,%s,%s)
                    """, [(rev[0],) + change for change in changes])
        cursor.execute("""
            UPDATE repository SET value=%s WHERE id=1 AND name='youngest_rev'
            """, (args[-1][0][0],))

    # Tests

    def test_initial_sync_with_empty_repos(self):
        repos = self.get_repos()
        cache = CachedRepository(self.env, repos, self.log)
        cache.sync()

        cursor = self.db.cursor()
        cursor.execute("SELECT rev,time,author,message FROM revision")
        self.assertEquals(None, cursor.fetchone())
        cursor.execute("SELECT COUNT(*) FROM node_change")
        self.assertEquals(0, cursor.fetchone()[0])

    def test_initial_sync(self):
        t1 = datetime(2001, 1, 1, 1, 1, 1, 0, utc)
        t2 = datetime(2002, 1, 1, 1, 1, 1, 0, utc)
        repos = self.get_repos(get_changeset=lambda x: changesets[int(x)],
                               youngest_rev=1)
        changes = [('trunk', Node.DIRECTORY, Changeset.ADD, None, None),
                   ('trunk/README', Node.FILE, Changeset.ADD, None, None)]
        changesets = [Mock(Changeset, repos, 0, '', '', t1,
                           get_changes=lambda: []),
                      Mock(Changeset, repos, 1, 'Import', 'joe', t2,
                           get_changes=lambda: iter(changes))]
        cache = CachedRepository(self.env, repos, self.log)
        cache.sync()

        cursor = self.db.cursor()
        cursor.execute("SELECT rev,time,author,message FROM revision")
        self.assertEquals(('0', to_utimestamp(t1), '', ''),
                          cursor.fetchone())
        self.assertEquals(('1', to_utimestamp(t2), 'joe', 'Import'),
                          cursor.fetchone())
        self.assertEquals(None, cursor.fetchone())
        cursor.execute("""
            SELECT rev,path,node_type,change_type,base_path,base_rev
            FROM node_change
            """)
        self.assertEquals(('1', 'trunk', 'D', 'A', None, None),
                          cursor.fetchone())
        self.assertEquals(('1', 'trunk/README', 'F', 'A', None, None),
                          cursor.fetchone())
        self.assertEquals(None, cursor.fetchone())

    def test_update_sync(self):
        t1 = datetime(2001, 1, 1, 1, 1, 1, 0, utc)
        t2 = datetime(2002, 1, 1, 1, 1, 1, 0, utc)
        t3 = datetime(2003, 1, 1, 1, 1, 1, 0, utc)
        self.preset_cache(
            (('0', to_utimestamp(t1), '', ''), []),
            (('1', to_utimestamp(t2), 'joe', 'Import'),
             [('trunk', 'D', 'A', None, None),
              ('trunk/README', 'F', 'A', None, None)]),
            )
        repos = self.get_repos(get_changeset=lambda x: changesets[int(x)],
                               youngest_rev=2)
        changes = [('trunk/README', Node.FILE, Changeset.EDIT, 'trunk/README',
                    1)]
        changesets = [
            None,
            Mock(Changeset, repos, 1, '', '', t2, get_changes=lambda: []),
            Mock(Changeset, repos, 2, 'Update', 'joe', t3,
                 get_changes=lambda: iter(changes))
            ]
        cache = CachedRepository(self.env, repos, self.log)
        cache.sync()

        cursor = self.db.cursor()
        cursor.execute("""
            SELECT time,author,message FROM revision WHERE rev='2'
            """)
        self.assertEquals((to_utimestamp(t3), 'joe', 'Update'),
                          cursor.fetchone())
        self.assertEquals(None, cursor.fetchone())
        cursor.execute("""
            SELECT path,node_type,change_type,base_path,base_rev
            FROM node_change WHERE rev='2'
            """)
        self.assertEquals(('trunk/README', 'F', 'E', 'trunk/README', '1'),
                          cursor.fetchone())
        self.assertEquals(None, cursor.fetchone())

    def test_clean_sync(self):
        t1 = datetime(2001, 1, 1, 1, 1, 1, 0, utc)
        t2 = datetime(2002, 1, 1, 1, 1, 1, 0, utc)
        t3 = datetime(2003, 1, 1, 1, 1, 1, 0, utc)
        self.preset_cache(
            (('0', to_utimestamp(t1), '', ''), []),
            (('1', to_utimestamp(t2), 'joe', 'Import'),
             [('trunk', 'D', 'A', None, None),
              ('trunk/README', 'F', 'A', None, None)]),
            )
        repos = self.get_repos(get_changeset=lambda x: changesets[int(x)],
                               youngest_rev=2)
        changes1 = [('trunk', Node.DIRECTORY, Changeset.ADD, None, None),
                    ('trunk/README', Node.FILE, Changeset.ADD, None, None)]
        changes2 = [('trunk/README', Node.FILE, Changeset.EDIT, 'trunk/README',
                     1)]
        changesets = [
            Mock(Changeset, repos, 0, '**empty**', 'joe', t1,
                 get_changes=lambda: []),
            Mock(Changeset, repos, 1, 'Initial Import', 'joe', t2,
                 get_changes=lambda: iter(changes1)),
            Mock(Changeset, repos, 2, 'Update', 'joe', t3,
                 get_changes=lambda: iter(changes2))
            ]
        cache = CachedRepository(self.env, repos, self.log)
        cache.sync(clean=True)

        cursor = self.db.cursor()
        cursor.execute("SELECT time,author,message FROM revision ORDER BY rev")
        self.assertEquals((to_utimestamp(t1), 'joe', '**empty**'),
                          cursor.fetchone())
        self.assertEquals((to_utimestamp(t2), 'joe', 'Initial Import'),
                          cursor.fetchone())
        self.assertEquals((to_utimestamp(t3), 'joe', 'Update'),
                          cursor.fetchone())
        self.assertEquals(None, cursor.fetchone())
        cursor.execute("""
            SELECT rev,path,node_type,change_type,base_path,base_rev
            FROM node_change ORDER BY rev, path
            """)
        self.assertEquals(('1', 'trunk', 'D', 'A', None, None),
                          cursor.fetchone())
        self.assertEquals(('1', 'trunk/README', 'F', 'A', None, None),
                          cursor.fetchone())
        self.assertEquals(('2', 'trunk/README', 'F', 'E',
                           'trunk/README', '1'),
                          cursor.fetchone())
        self.assertEquals(None, cursor.fetchone())

    def test_sync_changeset(self):
        t1 = datetime(2001, 1, 1, 1, 1, 1, 0, utc)
        t2 = datetime(2002, 1, 1, 1, 1, 1, 0, utc)
        self.preset_cache(
            (('0', to_utimestamp(t1), '', ''), []),
            (('1', to_utimestamp(t2), 'joe', 'Import'),
             [('trunk', 'D', 'A', None, None),
              ('trunk/README', 'F', 'A', None, None)]),
            )
        repos = self.get_repos(get_changeset=lambda x: changesets[int(x)],
                               youngest_rev=1)
        changes1 = [('trunk', Node.DIRECTORY, Changeset.ADD, None, None),
                    ('trunk/README', Node.FILE, Changeset.ADD, None, None)]
        changesets = [
            Mock(Changeset, repos, 0, '**empty**', 'joe', t1,
                 get_changes=lambda: []),
            Mock(Changeset, repos, 1, 'Initial Import', 'joe', t2,
                 get_changes=lambda: iter(changes1)),
            ]
        cache = CachedRepository(self.env, repos, self.log)
        cache.sync_changeset(0)

        cursor = self.db.cursor()
        cursor.execute("SELECT time,author,message FROM revision ORDER BY rev")
        self.assertEquals((to_utimestamp(t1), 'joe', '**empty**'),
                          cursor.fetchone())
        self.assertEquals((to_utimestamp(t2), 'joe', 'Import'),
                          cursor.fetchone())
        self.assertEquals(None, cursor.fetchone())

    def test_sync_changeset_if_not_exists(self):
        t = [
            datetime(2001, 1, 1, 1, 1, 1, 0, utc), # r0
            datetime(2002, 1, 1, 1, 1, 1, 0, utc), # r1
            datetime(2003, 1, 1, 1, 1, 1, 0, utc), # r2
            datetime(2004, 1, 1, 1, 1, 1, 0, utc), # r3
        ]
        self.preset_cache(
            (('0', to_utimestamp(t[0]), 'joe', '**empty**'), []),
            (('1', to_utimestamp(t[1]), 'joe', 'Import'),
             [('trunk', 'D', 'A', None, None),
              ('trunk/README', 'F', 'A', None, None)]),
            # not exists r2
            (('3', to_utimestamp(t[3]), 'joe', 'Add COPYING'),
             [('trunk/COPYING', 'F', 'A', None, None)]),
            )
        repos = self.get_repos(get_changeset=lambda x: changesets[int(x)],
                               youngest_rev=3)
        changes = [
            None,                                                       # r0
            [('trunk', Node.DIRECTORY, Changeset.ADD, None, None),      # r1
             ('trunk/README', Node.FILE, Changeset.ADD, None, None)],
            [('branches', Node.DIRECTORY, Changeset.ADD, None, None),   # r2
             ('tags', Node.DIRECTORY, Changeset.ADD, None, None)],
            [('trunk/COPYING', Node.FILE, Changeset.ADD, None, None)],  # r3
        ]
        changesets = [
            Mock(Changeset, repos, 0, '**empty**', 'joe', t[0],
                 get_changes=lambda: []),
            Mock(Changeset, repos, 1, 'Initial Import', 'joe', t[1],
                 get_changes=lambda: iter(changes[1])),
            Mock(Changeset, repos, 2, 'Created directories', 'john', t[2],
                 get_changes=lambda: iter(changes[2])),
            Mock(Changeset, repos, 3, 'Add COPYING', 'joe', t[3],
                 get_changes=lambda: iter(changes[3])),
            ]
        cache = CachedRepository(self.env, repos, self.log)
        self.assertRaises(NoSuchChangeset, cache.get_changeset, 2)
        cache.sync()
        self.assertRaises(NoSuchChangeset, cache.get_changeset, 2)

        self.assertEqual(None, cache.sync_changeset(2))
        cset = cache.get_changeset(2)
        self.assertEqual('john', cset.author)
        self.assertEqual('Created directories', cset.message)
        self.assertEqual(t[2], cset.date)
        cset_changes = cset.get_changes()
        self.assertEqual(('branches', Node.DIRECTORY, Changeset.ADD, None,
                          None),
                         cset_changes.next())
        self.assertEqual(('tags', Node.DIRECTORY, Changeset.ADD, None, None),
                         cset_changes.next())
        self.assertRaises(StopIteration, cset_changes.next)

        cursor = self.db.cursor()
        cursor.execute("SELECT time,author,message FROM revision ORDER BY rev")
        self.assertEquals((to_utimestamp(t[0]), 'joe', '**empty**'),
                          cursor.fetchone())
        self.assertEquals((to_utimestamp(t[1]), 'joe', 'Import'),
                          cursor.fetchone())
        self.assertEquals((to_utimestamp(t[2]), 'john', 'Created directories'),
                          cursor.fetchone())
        self.assertEquals((to_utimestamp(t[3]), 'joe', 'Add COPYING'),
                          cursor.fetchone())
        self.assertEquals(None, cursor.fetchone())

    def test_sync_changeset_with_string_rev(self):  # ticket:11660

        class MockCachedRepository(CachedRepository):
            def db_rev(self, rev):
                return '%010d' % rev

        t1 = datetime(2001, 1, 1, 1, 1, 1, 0, utc)
        t2 = datetime(2002, 1, 1, 1, 1, 1, 0, utc)
        repos = self.get_repos(get_changeset=lambda x: changesets[int(x)],
                               youngest_rev=1)
        changesets = [
            Mock(Changeset, repos, 0, 'empty', 'joe', t1,
                 get_changes=lambda: []),
            Mock(Changeset, repos, 1, 'first', 'joe', t2,
                 get_changes=lambda: []),
            ]
        cache = MockCachedRepository(self.env, repos, self.log)
        cursor = self.db.cursor()

        cache.sync_changeset('0')   # not cached yet
        cache.sync_changeset(u'1')  # not cached yet
        cursor.execute("SELECT rev,author FROM revision ORDER BY rev")
        self.assertEquals(('0000000000', 'joe'), cursor.fetchone())
        self.assertEquals(('0000000001', 'joe'), cursor.fetchone())
        self.assertEquals(None, cursor.fetchone())

        cache.sync_changeset(u'0')  # cached
        cache.sync_changeset('1')   # cached
        cursor.execute("SELECT rev,author FROM revision ORDER BY rev")
        self.assertEquals(('0000000000', 'joe'), cursor.fetchone())
        self.assertEquals(('0000000001', 'joe'), cursor.fetchone())
        self.assertEquals(None, cursor.fetchone())

    def test_get_changes(self):
        t1 = datetime(2001, 1, 1, 1, 1, 1, 0, utc)
        t2 = datetime(2002, 1, 1, 1, 1, 1, 0, utc)
        self.preset_cache(
            (('0', to_utimestamp(t1), '', ''), []),
            (('1', to_utimestamp(t2), 'joe', 'Import'),
             [('trunk', 'D', 'A', None, None),
              ('trunk/RDME', 'F', 'A', None, None)]),
            )
        repos = self.get_repos()
        cache = CachedRepository(self.env, repos, self.log)
        self.assertEqual('1', cache.youngest_rev)
        changeset = cache.get_changeset(1)
        self.assertEqual('joe', changeset.author)
        self.assertEqual('Import', changeset.message)
        self.assertEqual(t2, changeset.date)
        changes = changeset.get_changes()
        self.assertEqual(('trunk', Node.DIRECTORY, Changeset.ADD, None, None),
                         changes.next())
        self.assertEqual(('trunk/RDME', Node.FILE, Changeset.ADD, None, None),
                         changes.next())
        self.assertRaises(StopIteration, changes.next)


def suite():
    return unittest.makeSuite(CacheTestCase, 'test')

if __name__ == '__main__':
    unittest.main()
