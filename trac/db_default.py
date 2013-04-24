# -*- coding: utf-8 -*-
#
# Copyright (C) 2003-2009 Edgewall Software
# Copyright (C) 2003-2005 Daniel Lundin <daniel@edgewall.com>
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
# Author: Daniel Lundin <daniel@edgewall.com>

from trac.db import Table, Column, Index

# Database version identifier. Used for automatic upgrades.
db_version = 26

def __mkreports(reports):
    """Utility function used to create report data in same syntax as the
    default data. This extra step is done to simplify editing the default
    reports."""
    result = []
    for report in reports:
        result.append((None, report[0], report[2], report[1]))
    return result


##
## Database schema
##

schema = [
    # Common
    Table('system', key='name')[
        Column('name'),
        Column('value')],
    Table('permission', key=('username', 'action'))[
        Column('username'),
        Column('action')],
    Table('auth_cookie', key=('cookie', 'ipnr', 'name'))[
        Column('cookie'),
        Column('name'),
        Column('ipnr'),
        Column('time', type='int')],
    Table('session', key=('sid', 'authenticated'))[
        Column('sid'),
        Column('authenticated', type='int'),
        Column('last_visit', type='int'),
        Index(['last_visit']),
        Index(['authenticated'])],
    Table('session_attribute', key=('sid', 'authenticated', 'name'))[
        Column('sid'),
        Column('authenticated', type='int'),
        Column('name'),
        Column('value')],
    Table('cache', key='id')[
        Column('id'),
        Column('generation', type='int')],

    # Attachments
    Table('attachment', key=('type', 'id', 'filename'))[
        Column('type'),
        Column('id'),
        Column('filename'),
        Column('size', type='int'),
        Column('time', type='int64'),
        Column('description'),
        Column('author'),
        Column('ipnr')],

    # Wiki system
    Table('wiki', key=('name', 'version'))[
        Column('name'),
        Column('version', type='int'),
        Column('time', type='int64'),
        Column('author'),
        Column('ipnr'),
        Column('text'),
        Column('comment'),
        Column('readonly', type='int'),
        Index(['time'])],

    # Version control cache
    Table('repository', key=('id', 'name'))[
        Column('id', type='int'),
        Column('name'),
        Column('value')],
    Table('revision', key=('repos', 'rev'))[
        Column('repos', type='int'),
        Column('rev', key_size=20),
        Column('time', type='int64'),
        Column('author'),
        Column('message'),
        Index(['repos', 'time'])],
    Table('node_change', key=('repos', 'rev', 'path', 'change_type'))[
        Column('repos', type='int'),
        Column('rev', key_size=20),
        Column('path', key_size=255),
        Column('node_type', size=1),
        Column('change_type', size=1, key_size=2),
        Column('base_path'),
        Column('base_rev'),
        Index(['repos', 'rev'])],

    # Ticket system
    Table('ticket', key='id')[
        Column('id', auto_increment=True),
        Column('type'),
        Column('time', type='int64'),
        Column('changetime', type='int64'),
        Column('component'),
        Column('severity'),
        Column('priority'),
        Column('owner'),
        Column('reporter'),
        Column('cc'),
        Column('version'),
        Column('milestone'),
        Column('status'),
        Column('resolution'),
        Column('summary'),
        Column('description'),
        Column('keywords'),
        Index(['time']),
        Index(['status'])],    
    Table('ticket_change', key=('ticket', 'time', 'field'))[
        Column('ticket', type='int'),
        Column('time', type='int64'),
        Column('author'),
        Column('field'),
        Column('oldvalue'),
        Column('newvalue'),
        Index(['ticket']),
        Index(['time'])],
    Table('ticket_custom', key=('ticket', 'name'))[
        Column('ticket', type='int'),
        Column('name'),
        Column('value')],
    Table('enum', key=('type', 'name'))[
        Column('type'),
        Column('name'),
        Column('value')],
    Table('component', key='name')[
        Column('name'),
        Column('owner'),
        Column('description')],
    Table('milestone', key='name')[
        Column('name'),
        Column('due', type='int64'),
        Column('completed', type='int64'),
        Column('description')],
    Table('version', key='name')[
        Column('name'),
        Column('time', type='int64'),
        Column('description')],

    # Report system
    Table('report', key='id')[
        Column('id', auto_increment=True),
        Column('author'),
        Column('title'),
        Column('query'),
        Column('description')],
]


##
## Default Reports
##

def get_reports(db):
    return (
(u'未解決チケット',
u"""
 * 全コンポーネント、全バージョンの未解決チケットを優先度順に表示します。
 * 優先度別の色付けを行っています。
""",
u"""
SELECT p.value AS __color__,
   id AS ticket, summary AS 概要, component AS コンポーネント,
   version AS バージョン, milestone AS マイルストーン, t.type AS 分類,
   owner AS 担当者, status AS ステータス, time AS 登録日付,
   changetime AS _更新日付, description AS _説明,
   reporter AS _報告者
  FROM ticket t
  LEFT JOIN enum p ON p.name = t.priority AND p.type = 'priority'
  WHERE status <> 'closed'
  ORDER BY """ + db.cast('p.value', 'int') + """, milestone, t.type, time
"""),
#----------------------------------------------------------------------------
 (u'未解決チケット (バージョン別)',
u"""
このレポートはバージョン別にグルーピングする時、
優先度に色付けを行うやり方の例です。

最終更新日時、チケットの説明、報告者が隠しフィールドとして含まれています。
これらのフィールドは Web ブラウザでは表示されませんが、 RSS には出力されます。
""",
u"""
SELECT p.value AS __color__,
   version AS __group__,
   id AS ticket, summary AS 概要, component AS コンポーネント,
   milestone AS マイルストーン, t.type AS 分類,
   owner AS 担当者, status AS ステータス, time AS 登録日付,
   changetime AS _更新日付, description AS _説明,
   reporter AS _報告者
  FROM ticket t
  LEFT JOIN enum p ON p.name = t.priority AND p.type = 'priority'
  WHERE status <> 'closed'
  ORDER BY (version IS NULL),version, """ + db.cast('p.value', 'int') +
  """, t.type, time
"""),
#----------------------------------------------------------------------------
(u'未解決チケット (マイルストーン別)',
u"""
このレポートはマイルストーン別にグルーピングする時、
優先度に色付けを行うやり方の例です。

最終更新日時、チケットの説明、報告者が隠しフィールドとして含まれています。
これらのフィールドは Web ブラウザでは表示されませんが、 RSS には出力されます。
""",
u"""
SELECT p.value AS __color__,
   %s AS __group__,
   id AS ticket, summary AS 概要, component AS コンポーネント,
   version AS バージョン, t.type AS 分類,
   owner AS 担当者, status AS ステータス, time AS 登録日付,
   changetime AS _更新日付, description AS _説明,
   reporter AS _報告者
  FROM ticket t
  LEFT JOIN enum p ON p.name = t.priority AND p.type = 'priority'
  WHERE status <> 'closed' 
  ORDER BY (milestone IS NULL),milestone, %s, t.type, time
""" % (db.concat(u"'マイルストーン '", 'milestone'), db.cast('p.value', 'int'))),
#----------------------------------------------------------------------------
(u'着手中の未解決チケット (担当者別)',
u"""
担当者別に優先度順に並べた、着手中の未解決チケットの一覧です。
""",
u"""
SELECT p.value AS __color__,
   owner AS __group__,
   id AS ticket, summary AS 概要, component AS コンポーネント,
   milestone AS マイルストーン, t.type AS 分類, time AS 登録日付,
   changetime AS _更新日付, description AS _説明,
   reporter AS _報告者
  FROM ticket t
  LEFT JOIN enum p ON p.name = t.priority AND p.type = 'priority'
  WHERE status = 'accepted'
  ORDER BY owner, """ + db.cast('p.value', 'int') + """, t.type, time
"""),
#----------------------------------------------------------------------------
(u'着手中の未解決チケット (担当者別, 説明文付き)',
u"""
担当者別に優先度順に並べた、着手中の未解決チケットの一覧です。
このレポートでは、全列結合表示を使用しています。
""",
u"""
SELECT p.value AS __color__,
   owner AS __group__,
   id AS ticket, summary AS 概要, component AS コンポーネント,
   milestone AS マイルストーン, t.type AS 分類, time AS 登録日付,
   description AS _説明_,
   changetime AS _更新日付, reporter AS _報告者
  FROM ticket t
  LEFT JOIN enum p ON p.name = t.priority AND p.type = 'priority'
  WHERE status = 'accepted'
  ORDER BY owner, """ + db.cast('p.value', 'int') + """, t.type, time
"""),
#----------------------------------------------------------------------------
(u'全チケット (マイルストーン別, 解決済みも含む)',
u"""
高度なレポートを作成するための例です。
""",
u"""
SELECT p.value AS __color__,
   t.milestone AS __group__,
   (CASE status 
      WHEN 'closed' THEN 'color: #777; background: #ddd; border-color: #ccc;'
      ELSE 
        (CASE owner WHEN $USER THEN 'font-weight: bold' END)
    END) AS __style__,
   id AS ticket, summary AS 概要, component AS コンポーネント,
   status AS ステータス, resolution AS 解決方法, version AS バージョン,
   t.type AS 分類, priority AS 優先度, owner AS 担当者,
   changetime AS 更新日付,
   time AS _登録日付, reporter AS _報告者
  FROM ticket t
  LEFT JOIN enum p ON p.name = t.priority AND p.type = 'priority'
  ORDER BY (milestone IS NULL), milestone DESC, (status = 'closed'), 
        (CASE status WHEN 'closed' THEN changetime ELSE (-1) * %s END) DESC
""" % db.cast('p.value', 'int')),
#----------------------------------------------------------------------------
(u'自分のチケット',
u"""
このレポートは、実行される際のログインユーザ名で、
動的に置き換えられる変数 USER を
使用した例です。
""",
u"""
SELECT p.value AS __color__,
   (CASE status WHEN 'accepted' THEN '着手中' ELSE '担当中' END) AS __group__,
   id AS ticket, summary AS 概要, component AS コンポーネント,
   version AS バージョン, milestone AS マイルストーン, t.type AS 分類,
   priority AS 優先度, time AS created,
   changetime AS _changetime, description AS _説明,
   reporter AS _報告者
  FROM ticket t
  LEFT JOIN enum p ON p.name = t.priority AND p.type = 'priority'
  WHERE t.status <> 'closed' AND owner = $USER
  ORDER BY (status = 'accepted') DESC, """ + db.cast('p.value', 'int') + 
  """, milestone, t.type, time
"""),
#----------------------------------------------------------------------------
(u'未解決チケット (自分のチケットを優先して表示)',
u"""
 * 全ての未解決チケットを優先度順に表示します。
 * ログインユーザが担当者になっているチケットを最初のグループで表示します。
""",
u"""
SELECT p.value AS __color__,
   (CASE owner
     WHEN $USER THEN '自分のチケット'
     ELSE '未解決チケット'
    END) AS __group__,
   id AS ticket, summary AS 概要, component AS コンポーネント,
   version AS バージョン, milestone AS マイルストーン, t.type AS 分類,
   owner AS 担当者, status AS ステータス,
   time AS 登録日付,
   changetime AS _更新日付, description AS _説明,
   reporter AS _報告者
  FROM ticket t
  LEFT JOIN enum p ON p.name = t.priority AND p.type = 'priority'
  WHERE status <> 'closed' 
  ORDER BY (COALESCE(owner, '') = $USER) DESC, """
  + db.cast('p.value', 'int') + """, milestone, t.type, time
"""))


##
## Default database values
##

# (table, (column1, column2), ((row1col1, row1col2), (row2col1, row2col2)))
def get_data(db):
    return (('component',
              ('name', 'owner'),
                (('component1', 'somebody'),
                 ('component2', 'somebody'))),
            ('milestone',
              ('name', 'due', 'completed'),
                (('milestone1', 0, 0),
                 ('milestone2', 0, 0),
                 ('milestone3', 0, 0),
                 ('milestone4', 0, 0))),
            ('version',
              ('name', 'time'),
                (('1.0', 0),
                 ('2.0', 0))),
            ('enum',
              ('type', 'name', 'value'),
                (('resolution', 'fixed', 1),
                 ('resolution', 'invalid', 2),
                 ('resolution', 'wontfix', 3),
                 ('resolution', 'duplicate', 4),
                 ('resolution', 'worksforme', 5),
                 ('priority', 'blocker', 1),
                 ('priority', 'critical', 2),
                 ('priority', 'major', 3),
                 ('priority', 'minor', 4),
                 ('priority', 'trivial', 5),
                 ('ticket_type', 'defect', 1),
                 ('ticket_type', 'enhancement', 2),
                 ('ticket_type', 'task', 3))),
            ('permission',
              ('username', 'action'),
                (('anonymous', 'LOG_VIEW'),
                 ('anonymous', 'FILE_VIEW'),
                 ('anonymous', 'WIKI_VIEW'),
                 ('authenticated', 'WIKI_CREATE'),
                 ('authenticated', 'WIKI_MODIFY'),
                 ('anonymous', 'SEARCH_VIEW'),
                 ('anonymous', 'REPORT_VIEW'),
                 ('anonymous', 'REPORT_SQL_VIEW'),
                 ('anonymous', 'TICKET_VIEW'),
                 ('authenticated', 'TICKET_CREATE'),
                 ('authenticated', 'TICKET_MODIFY'),
                 ('anonymous', 'BROWSER_VIEW'),
                 ('anonymous', 'TIMELINE_VIEW'),
                 ('anonymous', 'CHANGESET_VIEW'),
                 ('anonymous', 'ROADMAP_VIEW'),
                 ('anonymous', 'MILESTONE_VIEW'))),
            ('system',
              ('name', 'value'),
                (('database_version', str(db_version)),
                 ('initial_database_version', str(db_version)))),
            ('report',
              ('author', 'title', 'query', 'description'),
                __mkreports(get_reports(db))))
