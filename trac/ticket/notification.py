# -*- coding: utf-8 -*-
#
# Copyright (C) 2003-2009 Edgewall Software
# Copyright (C) 2003-2005 Daniel Lundin <daniel@edgewall.com>
# Copyright (C) 2005-2006 Emmanuel Blot <emmanuel.blot@free.fr>
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
#

from unicodedata import east_asian_width

from genshi.template.text import NewTextTemplate

from trac.core import *
from trac.config import *
from trac.notification import NotifyEmail
from trac.ticket.api import TicketSystem
from trac.util import md5
from trac.util.datefmt import to_utimestamp
from trac.util.text import CRLF, wrap, obfuscate_email_address, to_unicode
from trac.util.translation import deactivate, reactivate

class TicketNotificationSystem(Component):

    always_notify_owner = BoolOption('notification', 'always_notify_owner',
                                     'false',
        """チケットの担当者 (owner) に常に通知メールを送信するかを設定します (''0.9 以降'') 。""")

    always_notify_reporter = BoolOption('notification',
                                        'always_notify_reporter',
                                        'false',
        """''報告者 (reporter)'' フィールドにあるアドレスに常に通知メールを
        送信するかを設定します。""")

    always_notify_updater = BoolOption('notification', 'always_notify_updater',
                                       'true',
        """チケット属性が変更された場合に、それまでの全ての変更を行った人に、
        常に通知メールを送信するかを設定します。""")
        
    ticket_subject_template = Option('notification', 'ticket_subject_template', 
                                     '$prefix #$ticket.id: $summary',
        """通知の件名 (Subject) に使用する Genshi のテキストテンプレートの一部を設定します。

        デフォルトでは件名のテンプレートは `$prefix #$ticket.id: $summary` です。
        `$prefix` の箇所は `smtp_subject_prefix` オプションの値で置き換えられます。
        (''0.11 以降'')""")

    ambiguous_char_width = Option('notification', 'ambiguous_char_width',
                                  'single',
        """幅の曖昧な文字 (例えば、'single' や 'double') が
        通知メールのテーブルに使えるようになりました。

        'single' の場合、US-ASCII 文字と同じ文字幅です。これは、
        ほとんどのユーザーから要求されています。
        'double' の場合、US-ASCII 文字の2倍の文字幅となります。これは、
        CJK ユーザーから要求されています。''(0.12.2 以降)''""")


class TicketNotifyEmail(NotifyEmail):
    """Notification of ticket changes."""

    template_name = "ticket_notify_email.txt"
    ticket = None
    newticket = None
    modtime = 0
    from_email = 'trac+ticket@localhost'
    COLS = 75

    def __init__(self, env):
        NotifyEmail.__init__(self, env)
        self.prev_cc = []
        self.ambiguous_char_width = env.config.get('notification',
                                                   'ambiguous_char_width',
                                                   'single')
        self.text_widths = {}

    def notify(self, ticket, newticket=True, modtime=None):
        """Send ticket change notification e-mail (untranslated)"""
        t = deactivate()
        translated_fields = ticket.fields
        try:
            ticket.fields = TicketSystem(self.env).get_ticket_fields()
            self._notify(ticket, newticket, modtime)
        finally:
            ticket.fields = translated_fields
            reactivate(t)

    def _notify(self, ticket, newticket=True, modtime=None):
        self.ticket = ticket
        self.modtime = modtime
        self.newticket = newticket

        changes_body = ''
        self.reporter = ''
        self.owner = ''
        changes_descr = ''
        change_data = {}
        link = self.env.abs_href.ticket(ticket.id)
        summary = self.ticket['summary']
        
        if not self.newticket and modtime:  # Ticket change
            from trac.ticket.web_ui import TicketModule
            for change in TicketModule(self.env).grouped_changelog_entries(
                                                ticket, self.db, when=modtime):
                if not change['permanent']: # attachment with same time...
                    continue
                change_data.update({
                    'author': obfuscate_email_address(change['author']),
                    'comment': wrap(change['comment'], self.COLS, ' ', ' ',
                                    CRLF)
                    })
                link += '#comment:%s' % str(change.get('cnum', ''))
                for field, values in change['fields'].iteritems():
                    old = values['old']
                    new = values['new']
                    newv = ''
                    if field == 'description':
                        new_descr = wrap(new, self.COLS, ' ', ' ', CRLF)
                        old_descr = wrap(old, self.COLS, '> ', '> ', CRLF)
                        old_descr = old_descr.replace(2 * CRLF, CRLF + '>' + \
                                                      CRLF)
                        cdescr = CRLF
                        cdescr += 'Old description:' + 2 * CRLF + old_descr + \
                                  2 * CRLF
                        cdescr += 'New description:' + 2 * CRLF + new_descr + \
                                  CRLF
                        changes_descr = cdescr
                    elif field == 'summary':
                        summary = "%s (was: %s)" % (new, old)
                    elif field == 'cc':
                        (addcc, delcc) = self.diff_cc(old, new)
                        chgcc = ''
                        if delcc:
                            chgcc += wrap(" * cc: %s (removed)" %
                                          ', '.join(delcc), 
                                          self.COLS, ' ', ' ', CRLF) + CRLF
                        if addcc:
                            chgcc += wrap(" * cc: %s (added)" %
                                          ', '.join(addcc), 
                                          self.COLS, ' ', ' ', CRLF) + CRLF
                        if chgcc:
                            changes_body += chgcc
                        self.prev_cc += old and self.parse_cc(old) or []
                    else:
                        if field in ['owner', 'reporter']:
                            old = obfuscate_email_address(old)
                            new = obfuscate_email_address(new)
                        newv = new
                        length = 7 + len(field)
                        spacer_old, spacer_new = ' ', ' '
                        if len(old + new) + length > self.COLS:
                            length = 5
                            if len(old) + length > self.COLS:
                                spacer_old = CRLF
                            if len(new) + length > self.COLS:
                                spacer_new = CRLF
                        chg = '* %s: %s%s%s=>%s%s' % (field, spacer_old, old,
                                                      spacer_old, spacer_new,
                                                      new)
                        chg = chg.replace(CRLF, CRLF + length * ' ')
                        chg = wrap(chg, self.COLS, '', length * ' ', CRLF)
                        changes_body += ' %s%s' % (chg, CRLF)
                    if newv:
                        change_data[field] = {'oldvalue': old, 'newvalue': new}
        
        ticket_values = ticket.values.copy()
        ticket_values['id'] = ticket.id
        ticket_values['description'] = wrap(
            ticket_values.get('description', ''), self.COLS,
            initial_indent=' ', subsequent_indent=' ', linesep=CRLF)
        ticket_values['new'] = self.newticket
        ticket_values['link'] = link
        
        subject = self.format_subj(summary)
        if not self.newticket:
            subject = 'Re: ' + subject
        self.data.update({
            'ticket_props': self.format_props(),
            'ticket_body_hdr': self.format_hdr(),
            'subject': subject,
            'ticket': ticket_values,
            'changes_body': changes_body,
            'changes_descr': changes_descr,
            'change': change_data
            })
        NotifyEmail.notify(self, ticket.id, subject)

    def format_props(self):
        tkt = self.ticket
        fields = [f for f in tkt.fields 
                  if f['name'] not in ('summary', 'cc', 'time', 'changetime')]
        width = [0, 0, 0, 0]
        i = 0
        for f in fields:
            if f['type'] == 'textarea':
                continue
            fname = f['name']
            if not fname in tkt.values:
                continue
            fval = tkt[fname] or ''
            if fval.find('\n') != -1:
                continue
            if fname in ['owner', 'reporter']:
                fval = obfuscate_email_address(fval)
            idx = 2 * (i % 2)
            width[idx] = max(self.get_text_width(f['label']), width[idx])
            width[idx + 1] = max(self.get_text_width(fval), width[idx + 1])
            i += 1
        width_l = width[0] + width[1] + 5
        width_r = width[2] + width[3] + 5
        half_cols = (self.COLS - 1) / 2
        if width_l + width_r + 1 > self.COLS:
            if ((width_l > half_cols and width_r > half_cols) or 
                    (width[0] > half_cols / 2 or width[2] > half_cols / 2)):
                width_l = half_cols
                width_r = half_cols
            elif width_l > width_r:
                width_l = min((self.COLS - 1) * 2 / 3, width_l)
                width_r = self.COLS - width_l - 1
            else:
                width_r = min((self.COLS - 1) * 2 / 3, width_r)         
                width_l = self.COLS - width_r - 1
        sep = width_l * '-' + '+' + width_r * '-'
        txt = sep + CRLF
        cell_tmp = [u'', u'']
        big = []
        i = 0
        width_lr = [width_l, width_r]
        for f in [f for f in fields if f['name'] != 'description']:
            fname = f['name']
            if not tkt.values.has_key(fname):
                continue
            fval = tkt[fname] or ''
            if fname in ['owner', 'reporter']:
                fval = obfuscate_email_address(fval)
            if f['type'] == 'textarea' or '\n' in unicode(fval):
                big.append((f['label'], CRLF.join(fval.splitlines())))
            else:
                # Note: f['label'] is a Babel's LazyObject, make sure its
                # __str__ method won't be called.
                str_tmp = u'%s:  %s' % (f['label'], unicode(fval))
                idx = i % 2
                cell_tmp[idx] += wrap(str_tmp, width_lr[idx] - 2 + 2 * idx,
                                      (width[2 * idx]
                                       - self.get_text_width(f['label'])
                                       + 2 * idx) * ' ',
                                      2 * ' ', CRLF)
                cell_tmp[idx] += CRLF
                i += 1
        cell_l = cell_tmp[0].splitlines()
        cell_r = cell_tmp[1].splitlines()
        for i in range(max(len(cell_l), len(cell_r))):
            if i >= len(cell_l):
                cell_l.append(width_l * ' ')
            elif i >= len(cell_r):
                cell_r.append('')
            fmt_width = width_l - self.get_text_width(cell_l[i]) \
                        + len(cell_l[i])
            txt += u'%-*s|%s%s' % (fmt_width, cell_l[i], cell_r[i], CRLF)
        if big:
            txt += sep
            for name, value in big:
                txt += CRLF.join(['', name + ':', value, '', ''])
        txt += sep
        return txt

    def parse_cc(self, txt):
        return filter(lambda x: '@' in x, txt.replace(',', ' ').split())

    def diff_cc(self, old, new):
        oldcc = NotifyEmail.addrsep_re.split(old)
        newcc = NotifyEmail.addrsep_re.split(new)
        added = [obfuscate_email_address(x) \
                                for x in newcc if x and x not in oldcc]
        removed = [obfuscate_email_address(x) \
                                for x in oldcc if x and x not in newcc]
        return (added, removed)

    def format_hdr(self):
        return '#%s: %s' % (self.ticket.id, wrap(self.ticket['summary'],
                                                 self.COLS, linesep=CRLF))

    def format_subj(self, summary):
        template = self.config.get('notification','ticket_subject_template')
        template = NewTextTemplate(template.encode('utf8'))
                                                
        prefix = self.config.get('notification', 'smtp_subject_prefix')
        if prefix == '__default__': 
            prefix = '[%s]' % self.env.project_name
        
        data = {
            'prefix': prefix,
            'summary': summary,
            'ticket': self.ticket,
            'env': self.env,
        }
        
        return template.generate(**data).render('text', encoding=None).strip()

    def get_recipients(self, tktid):
        notify_reporter = self.config.getbool('notification',
                                              'always_notify_reporter')
        notify_owner = self.config.getbool('notification',
                                           'always_notify_owner')
        notify_updater = self.config.getbool('notification', 
                                             'always_notify_updater')

        ccrecipients = self.prev_cc
        torecipients = []
        cursor = self.db.cursor()
        
        # Harvest email addresses from the cc, reporter, and owner fields
        cursor.execute("SELECT cc,reporter,owner FROM ticket WHERE id=%s",
                       (tktid,))
        row = cursor.fetchone()
        if row:
            ccrecipients += row[0] and row[0].replace(',', ' ').split() or []
            self.reporter = row[1]
            self.owner = row[2]
            if notify_reporter:
                torecipients.append(row[1])
            if notify_owner:
                torecipients.append(row[2])

        # Harvest email addresses from the author field of ticket_change(s)
        if notify_updater:
            cursor.execute("SELECT DISTINCT author,ticket FROM ticket_change "
                           "WHERE ticket=%s", (tktid,))
            for author, ticket in cursor:
                torecipients.append(author)

        # Suppress the updater from the recipients
        updater = None
        cursor.execute("SELECT author FROM ticket_change WHERE ticket=%s "
                       "ORDER BY time DESC LIMIT 1", (tktid,))
        for updater, in cursor:
            break
        else:
            cursor.execute("SELECT reporter FROM ticket WHERE id=%s",
                           (tktid,))
            for updater, in cursor:
                break

        if not notify_updater:
            filter_out = True
            if notify_reporter and (updater == self.reporter):
                filter_out = False
            if notify_owner and (updater == self.owner):
                filter_out = False
            if filter_out:
                torecipients = [r for r in torecipients if r and r != updater]
        elif updater:
            torecipients.append(updater)

        return (torecipients, ccrecipients)

    def get_message_id(self, rcpt, modtime=None):
        """Generate a predictable, but sufficiently unique message ID."""
        s = '%s.%08d.%d.%s' % (self.env.project_url.encode('utf-8'),
                               int(self.ticket.id), to_utimestamp(modtime),
                               rcpt.encode('ascii', 'ignore'))
        dig = md5(s).hexdigest()
        host = self.from_email[self.from_email.find('@') + 1:]
        msgid = '<%03d.%s@%s>' % (len(s), dig, host)
        return msgid

    def send(self, torcpts, ccrcpts):
        dest = self.reporter or 'anonymous'
        hdrs = {}
        hdrs['Message-ID'] = self.get_message_id(dest, self.modtime)
        hdrs['X-Trac-Ticket-ID'] = str(self.ticket.id)
        hdrs['X-Trac-Ticket-URL'] = self.data['ticket']['link']
        if not self.newticket:
            msgid = self.get_message_id(dest)
            hdrs['In-Reply-To'] = msgid
            hdrs['References'] = msgid
        NotifyEmail.send(self, torcpts, ccrcpts, hdrs)

    def get_text_width(self, text):
        ambiwidth = (1, 2)[self.ambiguous_char_width == 'double']
        text = to_unicode(text)

        if text in self.text_widths:
            return self.text_widths[text]

        width = 0
        for ch in text:
            eaw = east_asian_width(ch)
            if eaw in 'WF':
                width += 2
            elif eaw == 'A':
                width += ambiwidth
            else:
                width += 1
        self.text_widths[text] = width
        return width

