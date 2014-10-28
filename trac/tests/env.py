# -*- coding: utf-8 -*-
#
# Copyright (C) 2003-2013 Edgewall Software
# All rights reserved.
#
# This software is licensed as described in the file COPYING, which
# you should have received as part of this distribution. The terms
# are also available at http://trac.edgewall.org/wiki/TracLicense.
#
# This software consists of voluntary contributions made by many
# individuals. For the exact contribution history, see the revision
# history and logs, available at http://trac.edgewall.org/log/.

from __future__ import with_statement

from ConfigParser import RawConfigParser
import shutil
import tempfile
import unittest

import trac.tests.compat
from trac import db_default
from trac.core import ComponentManager
from trac.env import Environment
from trac.test import EnvironmentStub


class EnvironmentCreatedWithoutData(Environment):
    def __init__(self, path, create=False, options=[]):
        ComponentManager.__init__(self)

        self.path = path
        self.systeminfo = []
        self.href = self.abs_href = None

        if create:
            self.create(options)
        else:
            self.verify()
            self.setup_config()


class EmptyEnvironmentTestCase(unittest.TestCase):

    def setUp(self):
        env_path = tempfile.mkdtemp(prefix='trac-tempenv-')
        self.env = EnvironmentCreatedWithoutData(env_path, create=True)

    def tearDown(self):
        self.env.shutdown() # really closes the db connections
        shutil.rmtree(self.env.path)

    def test_get_version(self):
        """Testing env.get_version"""
        self.assertFalse(self.env.get_version())


class EnvironmentTestCase(unittest.TestCase):

    def setUp(self):
        env_path = tempfile.mkdtemp(prefix='trac-tempenv-')
        self.env = Environment(env_path, create=True)
        self.env.config.set('trac', 'base_url',
                            'http://trac.edgewall.org/some/path')
        self.env.config.save()

    def tearDown(self):
        self.env.shutdown() # really closes the db connections
        shutil.rmtree(self.env.path)

    def test_db_exc(self):
        db_exc = self.env.db_exc
        self.assertTrue(hasattr(db_exc, 'IntegrityError'))
        self.assertIs(db_exc, self.env.db_exc)

    def test_abs_href(self):
        abs_href = self.env.abs_href
        self.assertEqual('http://trac.edgewall.org/some/path', abs_href())
        self.assertIs(abs_href, self.env.abs_href)

    def test_href(self):
        href = self.env.href
        self.assertEqual('/some/path', href())
        self.assertIs(href, self.env.href)

    def test_get_version(self):
        """Testing env.get_version"""
        self.assertEqual(db_default.db_version, self.env.get_version())
        self.assertEqual(db_default.db_version, self.env.database_version)
        self.assertEqual(db_default.db_version, self.env.database_initial_version)

    def test_get_known_users(self):
        """Testing env.get_known_users"""
        with self.env.db_transaction as db:
            db.executemany("INSERT INTO session VALUES (%s,%s,0)",
                [('123', 0), ('tom', 1), ('joe', 1), ('jane', 1)])
            db.executemany("INSERT INTO session_attribute VALUES (%s,%s,%s,%s)",
                [('123', 0, 'email', 'a@example.com'),
                 ('tom', 1, 'name', 'Tom'),
                 ('tom', 1, 'email', 'tom@example.com'),
                 ('joe', 1, 'email', 'joe@example.com'),
                 ('jane', 1, 'name', 'Jane')])
        users = {}
        for username, name, email in self.env.get_known_users():
            users[username] = (name, email)

        self.assertTrue('anonymous' not in users)
        self.assertEqual(('Tom', 'tom@example.com'), users['tom'])
        self.assertEqual((None, 'joe@example.com'), users['joe'])
        self.assertEqual(('Jane', None), users['jane'])

    def test_is_component_enabled(self):
        self.assertEqual(True, Environment.required)
        self.assertEqual(True, self.env.is_component_enabled(Environment))
        self.assertEqual(False, EnvironmentStub.required)
        self.assertEqual(None, self.env.is_component_enabled(EnvironmentStub))

    def test_dumped_values_in_tracini(self):
        parser = RawConfigParser()
        filename = self.env.config.filename
        self.assertEqual([filename], parser.read(filename))
        self.assertEqual('#cc0,#0c0,#0cc,#00c,#c0c,#c00',
                         parser.get('revisionlog', 'graph_colors'))
        self.assertEqual('disabled', parser.get('trac', 'secure_cookies'))

    def test_dumped_values_in_tracini_sample(self):
        parser = RawConfigParser()
        filename = self.env.config.filename + '.sample'
        self.assertEqual([filename], parser.read(filename))
        self.assertEqual('#cc0,#0c0,#0cc,#00c,#c0c,#c00',
                         parser.get('revisionlog', 'graph_colors'))
        self.assertEqual('disabled', parser.get('trac', 'secure_cookies'))
        self.assertTrue(parser.has_option('logging', 'log_format'))
        self.assertEqual('', parser.get('logging', 'log_format'))


def suite():
    suite = unittest.TestSuite()
    suite.addTest(unittest.makeSuite(EnvironmentTestCase))
    suite.addTest(unittest.makeSuite(EmptyEnvironmentTestCase))
    return suite

if __name__ == '__main__':
    unittest.main(defaultTest='suite')
