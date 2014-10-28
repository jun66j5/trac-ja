# -*- coding: utf-8 -*-
#
# Copyright (C) 2012-2013 Edgewall Software
# All rights reserved.
#
# This software is licensed as described in the file COPYING, which
# you should have received as part of this distribution. The terms
# are also available at http://trac.edgewall.org/wiki/TracLicense.
#
# This software consists of voluntary contributions made by many
# individuals. For the exact contribution history, see the revision
# history and logs, available at http://trac.edgewall.org/log/.

import os
import tempfile
import unittest
try:
    from configobj import ConfigObj
except ImportError:
    ConfigObj = None

import trac.tests.compat
from trac.config import ConfigurationError
from trac.perm import PermissionCache
from trac.resource import Resource
from trac.test import EnvironmentStub, Mock
from trac.util import create_file
from trac.versioncontrol.api import Repository
from tracopt.perm.authz_policy import AuthzPolicy


class AuthzPolicyTestCase(unittest.TestCase):

    def setUp(self):
        tmpdir = os.path.realpath(tempfile.gettempdir())
        self.authz_file = os.path.join(tmpdir, 'trac-authz-policy')
        create_file(self.authz_file, """\
# Unicode user names
[groups]
administrators = éat

[wiki:WikiStart]
änon = WIKI_VIEW
@administrators = WIKI_VIEW
* =

# Unicode page names
[wiki:résumé]
änon =
@administrators = WIKI_VIEW
* =

# Tickets
[ticket:43]
änon = TICKET_VIEW
@administrators =
* =

[ticket:*]
änon =
@administrators = TICKET_VIEW
* =

# Default repository
[repository:@*]
änon =
@administrators = BROWSER_VIEW, FILE_VIEW
* =

# Non-default repository
[repository:bláh@*]
änon = BROWSER_VIEW, FILE_VIEW
@administrators = BROWSER_VIEW, FILE_VIEW
* =
""")
        self.env = EnvironmentStub(enable=['trac.*', AuthzPolicy], path=tmpdir)
        self.env.config.set('trac', 'permission_policies',
                            'AuthzPolicy, DefaultPermissionPolicy')
        self.env.config.set('authz_policy', 'authz_file', self.authz_file)
        self.authz_policy = AuthzPolicy(self.env)

    def tearDown(self):
        self.env.reset_db()
        os.remove(self.authz_file)

    def check_permission(self, action, user, resource, perm):
        return self.authz_policy.check_permission(action, user, resource, perm)

    def get_repository(self, reponame):
        params = {'id': 1, 'name': reponame}
        return Mock(Repository, 'mock', params, self.env.log)

    def get_perm(self, username, *args):
        perm = PermissionCache(self.env, username)
        if args:
            return perm(*args)
        return perm

    def test_unicode_username(self):
        resource = Resource('wiki', 'WikiStart')

        perm = self.get_perm('anonymous')
        self.assertEqual(
            False,
            self.check_permission('WIKI_VIEW', 'anonymous', resource, perm))
        self.assertNotIn('WIKI_VIEW', perm)
        self.assertNotIn('WIKI_VIEW', perm(resource))

        perm = self.get_perm(u'änon')
        self.assertEqual(
            True,
            self.check_permission('WIKI_VIEW', u'änon', resource, perm))
        self.assertNotIn('WIKI_VIEW', perm)
        self.assertIn('WIKI_VIEW', perm(resource))

    def test_unicode_resource_name(self):
        resource = Resource('wiki', u'résumé')

        perm = self.get_perm('anonymous')
        self.assertEqual(
            False,
            self.check_permission('WIKI_VIEW', 'anonymous', resource, perm))
        self.assertNotIn('WIKI_VIEW', perm)
        self.assertNotIn('WIKI_VIEW', perm(resource))

        perm = self.get_perm(u'änon')
        self.assertEqual(
            False,
            self.check_permission('WIKI_VIEW', u'änon', resource, perm))
        self.assertNotIn('WIKI_VIEW', perm)
        self.assertNotIn('WIKI_VIEW', perm(resource))

        perm = self.get_perm(u'éat')
        self.assertEqual(
            True,
            self.check_permission('WIKI_VIEW', u'éat', resource, perm))
        self.assertNotIn('WIKI_VIEW', perm)
        self.assertIn('WIKI_VIEW', perm(resource))

    def test_resource_without_id(self):
        perm = self.get_perm('anonymous')
        self.assertNotIn('TICKET_VIEW', perm)
        self.assertNotIn('TICKET_VIEW', perm('ticket'))
        self.assertNotIn('TICKET_VIEW', perm('ticket', 42))
        self.assertNotIn('TICKET_VIEW', perm('ticket', 43))

        perm = self.get_perm(u'änon')
        self.assertNotIn('TICKET_VIEW', perm)
        self.assertNotIn('TICKET_VIEW', perm('ticket'))
        self.assertNotIn('TICKET_VIEW', perm('ticket', 42))
        self.assertIn('TICKET_VIEW', perm('ticket', 43))

        perm = self.get_perm(u'éat')
        self.assertNotIn('TICKET_VIEW', perm)
        self.assertIn('TICKET_VIEW', perm('ticket'))
        self.assertIn('TICKET_VIEW', perm('ticket', 42))
        self.assertNotIn('TICKET_VIEW', perm('ticket', 43))

    def test_default_repository(self):
        repos = self.get_repository('')
        self.assertEqual(False, repos.is_viewable(self.get_perm('anonymous')))
        self.assertEqual(False, repos.is_viewable(self.get_perm(u'änon')))
        self.assertEqual(True, repos.is_viewable(self.get_perm(u'éat')))

    def test_non_default_repository(self):
        repos = self.get_repository(u'bláh')
        self.assertEqual(False, repos.is_viewable(self.get_perm('anonymous')))
        self.assertEqual(True, repos.is_viewable(self.get_perm(u'änon')))
        self.assertEqual(True, repos.is_viewable(self.get_perm(u'éat')))

    def test_case_sensitive_resource(self):
        resource = Resource('WIKI', 'wikistart')
        self.assertEqual(
            None,
            self.check_permission('WIKI_VIEW', 'anonymous', resource, None))
        self.assertEqual(
            None,
            self.check_permission('WIKI_VIEW', u'änon', resource, None))

    def test_get_authz_file(self):
        """get_authz_file should resolve a relative path and lazily compute.
        """
        authz_file = self.authz_policy.get_authz_file
        self.assertEqual(os.path.join(self.env.path, 'trac-authz-policy'),
                         authz_file)
        self.assertIs(authz_file, self.authz_policy.get_authz_file)

    def test_get_authz_file_notfound_raises(self):
        """ConfigurationError exception should be raised if file not found."""
        authz_file = os.path.join(self.env.path, 'some-nonexistent-file')
        self.env.config.set('authz_policy', 'authz_file', authz_file)
        self.assertRaises(ConfigurationError, getattr, self.authz_policy,
                          'get_authz_file')

    def test_get_authz_file_notdefined_raises(self):
        """ConfigurationError exception should be raised if the option
        `[authz_policy] authz_file` is not specified in trac.ini."""
        self.env.config.remove('authz_policy', 'authz_file')
        self.assertRaises(ConfigurationError, getattr, self.authz_policy,
                          'get_authz_file')

    def test_get_authz_file_empty_raises(self):
        """ConfigurationError exception should be raised if the option
        `[authz_policy] authz_file` is empty."""
        self.env.config.set('authz_policy', 'authz_file', '')
        self.assertRaises(ConfigurationError, getattr, self.authz_policy,
                          'get_authz_file')

    def test_parse_authz_empty(self):
        """Allow the file to be empty."""
        create_file(self.authz_file, '')
        self.authz_policy.parse_authz()
        self.assertFalse(self.authz_policy.authz)

    def test_parse_authz_no_settings(self):
        """Allow the file to have no settings."""
        create_file(self.authz_file, """\
# [wiki:WikiStart]
# änon = WIKI_VIEW
# * =
""")
        self.authz_policy.parse_authz()
        self.assertFalse(self.authz_policy.authz)

    def test_parse_authz_malformed_raises(self):
        """ConfigurationError should be raised if the file is malformed."""
        create_file(self.authz_file, """\
wiki:WikiStart]
änon = WIKI_VIEW
* =
""")
        self.assertRaises(ConfigurationError, self.authz_policy.parse_authz)

    def test_parse_authz_duplicated_sections_raises(self):
        """ConfigurationError should be raised if the file has duplicate
        sections."""
        create_file(self.authz_file, """\
[wiki:WikiStart]
änon = WIKI_VIEW

[wiki:WikiStart]
änon = WIKI_VIEW
""")
        self.assertRaises(ConfigurationError, self.authz_policy.parse_authz)


def suite():
    suite = unittest.TestSuite()
    if ConfigObj:
        suite.addTest(unittest.makeSuite(AuthzPolicyTestCase))
    else:
        print "SKIP: tracopt/perm/tests/authz_policy.py (no configobj " + \
              "installed)"
    return suite


if __name__ == '__main__':
    unittest.main(defaultTest='suite')
