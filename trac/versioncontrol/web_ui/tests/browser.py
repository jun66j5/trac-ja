# -*- coding: utf-8 -*-
#
# Copyright (C) 2014 Edgewall Software
# All rights reserved.
#
# This software is licensed as described in the file COPYING, which
# you should have received as part of this distribution. The terms
# are also available at http://trac.edgewall.com/license.html.
#
# This software consists of voluntary contributions made by many
# individuals. For the exact contribution history, see the revision
# history and logs, available at http://trac.edgewall.org/.

import unittest
from datetime import datetime
from cStringIO import StringIO

import trac.tests.compat
from trac.core import Component, TracError, implements
from trac.perm import PermissionError
from trac.resource import ResourceNotFound
from trac.test import EnvironmentStub, Mock, MockPerm
from trac.util.datefmt import utc
from trac.versioncontrol.api import (
    Changeset, DbRepositoryProvider, IRepositoryConnector, Node, NoSuchNode,
    Repository, RepositoryManager)
from trac.versioncontrol.web_ui.browser import BrowserModule
from trac.web.tests.api import RequestHandlerPermissionsTestCaseBase
from tracopt.perm.authz_policy import ConfigObj


class MockRepositoryConnector(Component):

    implements(IRepositoryConnector)

    def get_supported_types(self):
        yield 'mock', 8

    def get_repository(self, repos_type, repos_dir, params):
        def get_changeset(rev):
            return Mock(Changeset, repos, rev, 'message', 'author',
                        datetime(2001, 1, 1, tzinfo=utc))

        def get_node(path, rev):
            if 'missing' in path:
                raise NoSuchNode(path, rev)
            kind = Node.FILE if 'file' in path else Node.DIRECTORY
            node = Mock(Node, repos, path, rev, kind,
                        created_path=path, created_rev=rev,
                        get_entries=lambda: iter([]),
                        get_properties=lambda: {},
                        get_content=lambda: StringIO('content'),
                        get_content_length=lambda: 7,
                        get_content_type=lambda: 'application/octet-stream')
            return node

        if params['name'] == 'raise':
            raise TracError("")
        else:
            repos = Mock(Repository, params['name'], params, self.log,
                         get_youngest_rev=lambda: 1,
                         get_changeset=get_changeset,
                         get_node=get_node,
                         previous_rev=lambda rev, path='': None,
                         next_rev=lambda rev, path='': None)
        return repos


class BrowserModulePermissionsTestCase(RequestHandlerPermissionsTestCaseBase):

    authz_policy = """\
[repository:*allow*@*/source:*deny*]
anonymous = !BROWSER_VIEW, !FILE_VIEW

[repository:*deny*@*/source:*allow*]
anonymous = BROWSER_VIEW, FILE_VIEW

[repository:*allow*@*]
anonymous = BROWSER_VIEW, FILE_VIEW

[repository:*deny*@*]
anonymous = !BROWSER_VIEW, !FILE_VIEW

"""

    def setUp(self):
        super(BrowserModulePermissionsTestCase, self).setUp(BrowserModule)
        provider = DbRepositoryProvider(self.env)
        provider.add_repository('(default)', '/', 'mock')
        provider.add_repository('allow', '/', 'mock')
        provider.add_repository('deny', '/', 'mock')
        provider.add_repository('raise', '/', 'mock')

    def tearDown(self):
        RepositoryManager(self.env).reload_repositories()
        super(BrowserModulePermissionsTestCase, self).tearDown()

    def test_get_navigation_items_with_browser_view(self):
        self.grant_perm('anonymous', 'BROWSER_VIEW')
        provider = DbRepositoryProvider(self.env)
        req = self.create_request(path_info='/')
        self.assertEqual('browser', self.get_navigation_items(req).next()[1])

        provider.remove_repository('allow')
        self.assertEqual('browser', self.get_navigation_items(req).next()[1])

        provider.remove_repository('deny')
        self.assertEqual('browser', self.get_navigation_items(req).next()[1])

        provider.remove_repository('(default)')
        self.assertEqual([], list(self.get_navigation_items(req)))

    def test_get_navigation_items_without_browser_view(self):
        provider = DbRepositoryProvider(self.env)
        req = self.create_request(path_info='/')
        self.assertEqual('browser', self.get_navigation_items(req).next()[1])

        provider.remove_repository('(default)')
        self.assertEqual('browser', self.get_navigation_items(req).next()[1])

        provider.remove_repository('deny')
        self.assertEqual('browser', self.get_navigation_items(req).next()[1])

        provider.remove_repository('allow')
        self.assertEqual([], list(self.get_navigation_items(req)))

    def test_repository_with_browser_view(self):
        self.grant_perm('anonymous', 'BROWSER_VIEW')

        req = self.create_request(path_info='/browser/')
        rv = self.process_request(req)
        self.assertEqual('', rv[1]['repos'].name)

        req = self.create_request(path_info='/browser/allow')
        rv = self.process_request(req)
        self.assertEqual('allow', rv[1]['repos'].name)

        req = self.create_request(path_info='/browser/deny')
        try:
            self.process_request(req)
            self.fail('PermissionError not raised')
        except PermissionError, e:
            self.assertEqual('BROWSER_VIEW', e.action)
            self.assertEqual('source', e.resource.realm)
            self.assertEqual('/', e.resource.id)
            self.assertEqual('repository', e.resource.parent.realm)
            self.assertEqual('deny', e.resource.parent.id)

        DbRepositoryProvider(self.env).remove_repository('(default)')
        req = self.create_request(path_info='/browser/')
        rv = self.process_request(req)
        self.assertEqual(None, rv[1]['repos'])

        req = self.create_request(path_info='/browser/blah-blah-file')
        try:
            self.process_request(req)
            self.fail('ResourceNotFound not raised')
        except ResourceNotFound, e:
            self.assertEqual('No node blah-blah-file', unicode(e))

    def test_repository_without_browser_view(self):
        req = self.create_request(path_info='/browser/')
        rv = self.process_request(req)
        # cannot view default repository but don't raise PermissionError
        self.assertEqual(None, rv[1]['repos'])

        req = self.create_request(path_info='/browser/allow')
        rv = self.process_request(req)
        self.assertEqual('allow', rv[1]['repos'].name)

        req = self.create_request(path_info='/browser/deny')
        try:
            self.process_request(req)
            self.fail('PermissionError not raised')
        except PermissionError, e:
            self.assertEqual('BROWSER_VIEW', e.action)
            self.assertEqual('source', e.resource.realm)
            self.assertEqual('/', e.resource.id)
            self.assertEqual('repository', e.resource.parent.realm)
            self.assertEqual('deny', e.resource.parent.id)

        DbRepositoryProvider(self.env).remove_repository('(default)')
        req = self.create_request(path_info='/browser/')
        rv = self.process_request(req)
        self.assertEqual(None, rv[1]['repos'])

        req = self.create_request(path_info='/browser/blah-blah-file')
        try:
            self.process_request(req)
            self.fail('PermissionError not raised')
        except PermissionError, e:
            self.assertEqual('BROWSER_VIEW', e.action)
            self.assertEqual(None, e.resource)

    def test_node_with_file_view(self):
        self.grant_perm('anonymous', 'BROWSER_VIEW', 'FILE_VIEW')

        req = self.create_request(path_info='/browser/file')
        rv = self.process_request(req)
        self.assertEqual('', rv[1]['repos'].name)
        self.assertEqual('file', rv[1]['path'])

        req = self.create_request(path_info='/browser/allow-file')
        rv = self.process_request(req)
        self.assertEqual('', rv[1]['repos'].name)
        self.assertEqual('allow-file', rv[1]['path'])

        req = self.create_request(path_info='/browser/deny-file')
        try:
            self.process_request(req)
            self.fail('PermissionError not raised')
        except PermissionError, e:
            self.assertEqual('FILE_VIEW', e.action)
            self.assertEqual('source', e.resource.realm)
            self.assertEqual('deny-file', e.resource.id)
            self.assertEqual('repository', e.resource.parent.realm)
            self.assertEqual('', e.resource.parent.id)

    def test_node_in_allowed_repos_with_file_view(self):
        self.grant_perm('anonymous', 'BROWSER_VIEW', 'FILE_VIEW')

        req = self.create_request(path_info='/browser/allow/file')
        rv = self.process_request(req)
        self.assertEqual('allow', rv[1]['repos'].name)
        self.assertEqual('file', rv[1]['path'])

        req = self.create_request(path_info='/browser/allow/allow-file')
        rv = self.process_request(req)
        self.assertEqual('allow', rv[1]['repos'].name)
        self.assertEqual('allow-file', rv[1]['path'])

        req = self.create_request(path_info='/browser/allow/deny-file')
        try:
            self.process_request(req)
            self.fail('PermissionError not raised')
        except PermissionError, e:
            self.assertEqual('FILE_VIEW', e.action)
            self.assertEqual('source', e.resource.realm)
            self.assertEqual('deny-file', e.resource.id)
            self.assertEqual('repository', e.resource.parent.realm)
            self.assertEqual('allow', e.resource.parent.id)

    def test_node_in_denied_repos_with_file_view(self):
        self.grant_perm('anonymous', 'BROWSER_VIEW', 'FILE_VIEW')

        req = self.create_request(path_info='/browser/deny/allow-file')
        rv = self.process_request(req)
        self.assertEqual('deny', rv[1]['repos'].name)
        self.assertEqual('allow-file', rv[1]['path'])

        for path in ('file', 'deny-file'):
            req = self.create_request(path_info='/browser/deny/' + path)
            try:
                self.process_request(req)
                self.fail('PermissionError not raised (path: %r)' % path)
            except PermissionError, e:
                self.assertEqual('FILE_VIEW', e.action)
                self.assertEqual('source', e.resource.realm)
                self.assertEqual(path, e.resource.id)
                self.assertEqual('repository', e.resource.parent.realm)
                self.assertEqual('deny', e.resource.parent.id)

    def test_missing_node_with_browser_view(self):
        self.grant_perm('anonymous', 'BROWSER_VIEW')
        req = self.create_request(path_info='/browser/allow/missing')
        self.assertRaises(ResourceNotFound, self.process_request, req)
        req = self.create_request(path_info='/browser/deny/missing')
        self.assertRaises(ResourceNotFound, self.process_request, req)
        req = self.create_request(path_info='/browser/missing')
        self.assertRaises(ResourceNotFound, self.process_request, req)

    def test_missing_node_without_browser_view(self):
        req = self.create_request(path_info='/browser/allow/missing')
        self.assertRaises(ResourceNotFound, self.process_request, req)
        req = self.create_request(path_info='/browser/deny/missing')
        self.assertRaises(ResourceNotFound, self.process_request, req)
        req = self.create_request(path_info='/browser/missing')
        self.assertRaises(ResourceNotFound, self.process_request, req)

    def test_repository_index_with_hidden_default_repos(self):
        self.grant_perm('anonymous', 'BROWSER_VIEW', 'FILE_VIEW')
        provider = DbRepositoryProvider(self.env)
        provider.modify_repository('(default)', {'hidden': 'enabled'})
        req = self.create_request(path_info='/browser/')
        template, data, content_type = self.process_request(req)
        self.assertEqual(None, data['repos'])
        repo_data = data['repo']  # for repository index
        self.assertEqual('allow', repo_data['repositories'][0][0])
        self.assertEqual('raise', repo_data['repositories'][1][0])
        self.assertEqual(2, len(repo_data['repositories']))

    def test_node_in_hidden_default_repos(self):
        self.grant_perm('anonymous', 'BROWSER_VIEW', 'FILE_VIEW')
        provider = DbRepositoryProvider(self.env)
        provider.modify_repository('(default)', {'hidden': 'enabled'})
        req = self.create_request(path_info='/browser/blah-blah-file')
        template, data, content_type = self.process_request(req)
        self.assertEqual('', data['reponame'])
        self.assertEqual('blah-blah-file', data['path'])

    def test_no_viewable_repositories_with_browser_view(self):
        self.grant_perm('anonymous', 'BROWSER_VIEW')
        provider = DbRepositoryProvider(self.env)

        provider.remove_repository('allow')
        provider.remove_repository('(default)')
        provider.remove_repository('raise')

        req = self.create_request(path_info='/browser/')
        try:
            self.process_request(req)
            self.fail('ResourceNotFound not raised')
        except ResourceNotFound, e:
            self.assertEqual('No viewable repositories', unicode(e))
        req = self.create_request(path_info='/browser/allow/')
        try:
            self.process_request(req)
            self.fail('ResourceNotFound not raised')
        except ResourceNotFound, e:
            self.assertEqual('No node allow', unicode(e))
        req = self.create_request(path_info='/browser/deny/')
        try:
            self.process_request(req)
            self.fail('PermissionError not raised')
        except PermissionError, e:
            self.assertEqual('BROWSER_VIEW', e.action)
            self.assertEqual('source', e.resource.realm)
            self.assertEqual('/', e.resource.id)
            self.assertEqual('repository', e.resource.parent.realm)
            self.assertEqual('deny', e.resource.parent.id)

        provider.remove_repository('deny')
        req = self.create_request(path_info='/browser/')
        try:
            self.process_request(req)
            self.fail('ResourceNotFound not raised')
        except ResourceNotFound, e:
            self.assertEqual('No viewable repositories', unicode(e))
        req = self.create_request(path_info='/browser/deny/')
        try:
            self.process_request(req)
            self.fail('ResourceNotFound not raised')
        except ResourceNotFound, e:
            self.assertEqual('No node deny', unicode(e))

    def test_no_viewable_repositories_without_browser_view(self):
        provider = DbRepositoryProvider(self.env)
        provider.remove_repository('allow')
        req = self.create_request(path_info='/browser/')
        try:
            self.process_request(req)
            self.fail('PermissionError not raised')
        except PermissionError, e:
            self.assertEqual('BROWSER_VIEW', e.action)
            self.assertEqual(None, e.resource)
        provider.remove_repository('deny')
        provider.remove_repository('(default)')
        req = self.create_request(path_info='/browser/')
        try:
            self.process_request(req)
            self.fail('PermissionError not raised')
        except PermissionError, e:
            self.assertEqual('BROWSER_VIEW', e.action)
            self.assertEqual(None, e.resource)


def suite():
    suite = unittest.TestSuite()
    if ConfigObj:
        suite.addTest(unittest.makeSuite(BrowserModulePermissionsTestCase))
    else:
        print("SKIP: %s.%s (no configobj installed)" %
              (BrowserModulePermissionsTestCase.__module__,
               BrowserModulePermissionsTestCase.__name__))
    return suite


if __name__ == '__main__':
    unittest.main(defaultTest='suite')
