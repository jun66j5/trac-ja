#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (C) 2014-2015 Edgewall Software
# All rights reserved.
#
# This software is licensed as described in the file COPYING, which
# you should have received as part of this distribution. The terms
# are also available at http://trac.edgewall.org/wiki/TracLicense.

import StringIO
import warnings

from trac.util.text import print_table, printout

def _svn_version():
    from svn import core
    version = (core.SVN_VER_MAJOR, core.SVN_VER_MINOR,
               core.SVN_VER_MICRO)
    return '%d.%d.%d' % version + core.SVN_VER_TAG

PACKAGES = [
    ("Python",            'sys.version'),
    ("Setuptools",        'setuptools.__version__'),
    ("Genshi",            'genshi.__version__'),
    ("Babel",             'babel.__version__'),
    ("sqlite3",           'sqlite3.version'),
    ("PySqlite",          'pysqlite2.dbapi2.version'),
    ("MySQLdb",           'MySQLdb.__version__'),
    ("Psycopg2",          'psycopg2.__version__'),
    ("SVN bindings",      _svn_version),
    ("Mercurial",         'mercurial.util.version()'),
    ("Pygments",          'pygments.__version__'),
    ("Pytz",              'pytz.__version__'),
    ("ConfigObj",         'configobj.__version__'),
    ("Docutils",          'docutils.__version__'),
    ("Twill",             'twill.__version__'),
    ("LXML",              'lxml.etree.__version__'),
    ("coverage",          'coverage.__version__'),
    ("figleaf",           'figleaf.__version__'),
]

def package_versions(packages, out=None):
    name_version_pairs = []
    for name, accessor in packages:
        version = resolve_accessor(accessor)
        name_version_pairs.append((name, version))
    print_table(name_version_pairs, ("Package", "Version"), ' : ', out)

def resolve_accessor(accessor):
    if isinstance(accessor, basestring):
        def fn():
            module, attr = accessor.rsplit('.', 1)
            version = attr.replace('()', '')
            version = getattr(__import__(module, {}, {}, [version]), version)
            if attr.endswith('()'):
                version = version()
            return version
    else:
        fn = accessor
    try:
        return fn()
    except Exception:
        return "not installed"

def shift(prefix, block):
    return '\n'.join(prefix + line for line in block.split('\n') if line)

def print_status():
    warnings.filterwarnings('ignore', '', DeprecationWarning) # Twill 0.9...
    buf = StringIO.StringIO()
    package_versions(PACKAGES, buf)
    printout(shift('  ', buf.getvalue()))


if __name__ == '__main__':
    print_status()
