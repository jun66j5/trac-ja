# -*- coding: utf-8 -*-
#
# Copyright (C) 2005-2013 Edgewall Software
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
# Include a basic SMTP server, based on L. Smithson
# (lsmithson@open-networks.co.uk) extensible Python SMTP Server
#

import base64
import os
import quopri
import shutil
import tempfile
import re
import unittest
from datetime import datetime
from StringIO import StringIO

import trac.tests.compat
from trac.attachment import Attachment
from trac.test import EnvironmentStub, Mock, MockPerm
from trac.tests.notification import SMTP_TEST_PORT, SMTPThreadedServer,\
                                    parse_smtp_message
from trac.ticket.model import Ticket
from trac.ticket.notification import TicketNotifyEmail
from trac.ticket.web_ui import TicketModule
from trac.util.datefmt import utc

MAXBODYWIDTH = 76
notifysuite = None


class RecipientTestCase(unittest.TestCase):
    """Notification test cases for email recipients."""

    def setUp(self):
        self.env = EnvironmentStub(default_data=True)
        self.env.config.set('project', 'name', 'TracTest')
        self.env.config.set('notification', 'smtp_enabled', 'true')
        self.env.config.set('notification', 'smtp_port', str(SMTP_TEST_PORT))

    def tearDown(self):
        notifysuite.tear_down()
        self.env.reset_db()

    def test_no_recipients(self):
        """No recipient case"""
        ticket = Ticket(self.env)
        ticket['reporter'] = 'anonymous'
        ticket['summary'] = 'Foo'
        ticket.insert()
        tn = TicketNotifyEmail(self.env)
        tn.notify(ticket, newticket=True)
        recipients = notifysuite.smtpd.get_recipients()
        sender = notifysuite.smtpd.get_sender()
        message = notifysuite.smtpd.get_message()
        self.assertEqual(0, len(recipients))
        self.assertIsNone(sender)
        self.assertIsNone(message)

    def test_new_ticket_recipients(self):
        """Report and CC list should be in recipient list for new tickets."""
        always_cc = ('joe.user@example.net', 'joe.bar@example.net')
        ticket_cc = ('joe.user@example.com', 'joe.bar@example.org')
        self.env.config.set('notification', 'smtp_always_cc',
                            ', '.join(always_cc))
        ticket = Ticket(self.env)
        ticket['reporter'] = 'joe.bar@example.org'
        ticket['owner'] = 'joe.user@example.net'
        ticket['cc'] = ' '.join(ticket_cc)
        ticket['summary'] = 'New ticket recipients'
        ticket.insert()
        tn = TicketNotifyEmail(self.env)
        tn.notify(ticket, newticket=True)
        recipients = notifysuite.smtpd.get_recipients()
        for r in always_cc + ticket_cc + \
                (ticket['owner'], ticket['reporter']):
            self.assertIn(r, recipients)

    def test_cc_only(self):
        """Notification w/o explicit recipients but Cc: (#3101)"""
        always_cc = ('joe.user@example.net', 'joe.bar@example.net')
        self.env.config.set('notification', 'smtp_always_cc',
                            ', '.join(always_cc))
        ticket = Ticket(self.env)
        ticket['summary'] = 'Foo'
        ticket.insert()
        tn = TicketNotifyEmail(self.env)
        tn.notify(ticket, newticket=True)
        recipients = notifysuite.smtpd.get_recipients()
        for r in always_cc:
            self.assertIn(r, recipients)

    def test_always_notify_updater(self):
        """The `always_notify_updater` option."""
        def _test_updater(enabled):
            self.env.config.set('notification', 'always_notify_updater',
                                enabled)
            ticket = Ticket(self.env)
            ticket['reporter'] = 'joe.user@example.org'
            ticket['summary'] = u'This is a súmmäry'
            ticket.insert()
            now = datetime.now(utc)
            ticket.save_changes('joe.bar2@example.com', 'This is a change',
                                when=now)
            tn = TicketNotifyEmail(self.env)
            tn.notify(ticket, newticket=False, modtime=now)
            recipients = notifysuite.smtpd.get_recipients()
            if enabled:
                self.assertEqual(1, len(recipients))
                self.assertIn('joe.bar2@example.com', recipients)
            else:
                self.assertEqual(0, len(recipients))
                self.assertNotIn('joe.bar2@example.com', recipients)

        # Validate with and without a default domain
        for enable in False, True:
            _test_updater(enable)

    def test_always_notify_owner(self):
        """The `always_notify_owner` option."""
        def _test_reporter(enabled):
            self.env.config.set('notification', 'always_notify_owner',
                                enabled)
            self.env.config.set('notification', 'always_notify_updater',
                                'false')
            ticket = Ticket(self.env)
            ticket['summary'] = 'Foo'
            ticket['reporter'] = u'joe@example.org'
            ticket['owner'] = u'jim@example.org'
            ticket.insert()
            now = datetime.now(utc)
            ticket.save_changes('joe@example.org', 'this is my comment',
                                when=now)
            tn = TicketNotifyEmail(self.env)
            tn.notify(ticket, newticket=True, modtime=now)
            recipients = notifysuite.smtpd.get_recipients()
            if enabled:
                self.assertEqual(1, len(recipients))
                self.assertEqual('jim@example.org', recipients[0])
            else:
                self.assertEqual(0, len(recipients))

        for enable in False, True:
            _test_reporter(enable)

    def test_always_notify_reporter(self):
        """Notification to reporter w/ updater option disabled (#3780)"""
        def _test_reporter(enabled):
            self.env.config.set('notification', 'always_notify_updater',
                                'false')
            self.env.config.set('notification', 'always_notify_reporter',
                                enabled)
            ticket = Ticket(self.env)
            ticket['summary'] = 'Foo'
            ticket['reporter'] = u'joe@example.org'
            ticket.insert()
            now = datetime.now(utc)
            ticket.save_changes('joe@example.org', 'this is my comment',
                                when=now)
            tn = TicketNotifyEmail(self.env)
            tn.notify(ticket, newticket=True, modtime=now)
            recipients = notifysuite.smtpd.get_recipients()
            if enabled:
                self.assertEqual(1, len(recipients))
                self.assertEqual('joe@example.org', recipients[0])
            else:
                self.assertEqual(0, len(recipients))

        for enable in False, True:
            _test_reporter(enable)

    def test_no_duplicates(self):
        """Email addresses should be found only once in the recipient list."""
        self.env.config.set('notification', 'smtp_always_cc',
                            'joe.user@example.com')
        ticket = Ticket(self.env)
        ticket['reporter'] = 'joe.user@example.com'
        ticket['owner'] = 'joe.user@example.com'
        ticket['cc'] = 'joe.user@example.com'
        ticket['summary'] = 'No duplicates'
        ticket.insert()
        tn = TicketNotifyEmail(self.env)
        tn.notify(ticket, newticket=True)
        recipients = notifysuite.smtpd.get_recipients()
        self.assertEqual(1, len(recipients))
        self.assertIn('joe.user@example.com', recipients)

    def test_long_forms(self):
        """Long forms of SMTP email addresses 'Display Name <address>'"""
        self.env.config.set('notification', 'always_notify_owner', True)
        ticket = Ticket(self.env)
        ticket['reporter'] = '"Joe" <joe.user@example.com>'
        ticket['owner'] = 'Joe <joe.user@example.net>'
        ticket['cc'] = 'Joe < joe.user@example.org >'
        ticket['summary'] = 'Long form'
        ticket.insert()
        tn = TicketNotifyEmail(self.env)
        tn.notify(ticket, newticket=True)
        recipients = notifysuite.smtpd.get_recipients()
        self.assertEqual(3, len(recipients))
        self.assertIn('joe.user@example.com', recipients)
        self.assertIn('joe.user@example.net', recipients)
        self.assertIn('joe.user@example.org', recipients)


class NotificationTestCase(unittest.TestCase):
    """Notification test cases that send email over SMTP"""

    def setUp(self):
        self.env = EnvironmentStub(default_data=True)
        self.env.config.set('project', 'name', 'TracTest')
        self.env.config.set('notification', 'smtp_enabled', 'true')
        self.env.config.set('notification', 'always_notify_owner', 'true')
        self.env.config.set('notification', 'always_notify_reporter', 'true')
        self.env.config.set('notification', 'smtp_always_cc',
                            'joe.user@example.net, joe.bar@example.net')
        self.env.config.set('notification', 'use_public_cc', 'true')
        self.env.config.set('notification', 'smtp_port', str(SMTP_TEST_PORT))
        self.env.config.set('notification', 'smtp_server', 'localhost')
        self.req = Mock(href=self.env.href, abs_href=self.env.abs_href, tz=utc,
                        perm=MockPerm())

    def tearDown(self):
        """Signal the notification test suite that a test is over"""
        notifysuite.tear_down()
        self.env.reset_db()

    def test_structure(self):
        """Basic SMTP message structure (headers, body)"""
        ticket = Ticket(self.env)
        ticket['reporter'] = '"Joe User" <joe.user@example.org>'
        ticket['owner'] = 'joe.user@example.net'
        ticket['cc'] = 'joe.user@example.com, joe.bar@example.org, ' \
                       'joe.bar@example.net'
        ticket['summary'] = 'This is a summary'
        ticket.insert()
        tn = TicketNotifyEmail(self.env)
        tn.notify(ticket, newticket=True)
        message = notifysuite.smtpd.get_message()
        headers, body = parse_smtp_message(message)
        # checks for header existence
        self.assertTrue(headers)
        # checks for body existence
        self.assertTrue(body)
        # checks for expected headers
        self.assertIn('Date', headers)
        self.assertIn('Subject', headers)
        self.assertIn('Message-ID', headers)
        self.assertIn('From', headers)

    def test_date(self):
        """Date format compliance (RFC822)
           we do not support 'military' format"""
        date_str = r"^((?P<day>\w{3}),\s*)*(?P<dm>\d{2})\s+" \
                   r"(?P<month>\w{3})\s+(?P<year>\d{4})\s+" \
                   r"(?P<hour>\d{2}):(?P<min>[0-5][0-9])" \
                   r"(:(?P<sec>[0-5][0-9]))*\s" \
                   r"((?P<tz>\w{2,3})|(?P<offset>[+\-]\d{4}))$"
        date_re = re.compile(date_str)
        # python time module does not detect incorrect time values
        days = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
        months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
        tz = ['UT', 'GMT', 'EST', 'EDT', 'CST', 'CDT', 'MST', 'MDT',
              'PST', 'PDT']
        ticket = Ticket(self.env)
        ticket['reporter'] = '"Joe User" <joe.user@example.org>'
        ticket['summary'] = 'This is a summary'
        ticket.insert()
        tn = TicketNotifyEmail(self.env)
        tn.notify(ticket, newticket=True)
        message = notifysuite.smtpd.get_message()
        headers, body = parse_smtp_message(message)
        self.assertIn('Date', headers)
        mo = date_re.match(headers['Date'])
        self.assertTrue(mo)
        if mo.group('day'):
            self.assertIn(mo.group('day'), days)
        self.assertIn(int(mo.group('dm')), range(1, 32))
        self.assertIn(mo.group('month'), months)
        self.assertIn(int(mo.group('hour')), range(0, 24))
        if mo.group('tz'):
            self.assertIn(mo.group('tz'), tz)

    def test_bcc_privacy(self):
        """Visibility of recipients"""
        def run_bcc_feature(public_cc):
            # CC list should be private
            self.env.config.set('notification', 'use_public_cc', public_cc)
            self.env.config.set('notification', 'smtp_always_bcc',
                                'joe.foobar@example.net')
            ticket = Ticket(self.env)
            ticket['reporter'] = '"Joe User" <joe.user@example.org>'
            ticket['summary'] = 'This is a summary'
            ticket.insert()
            tn = TicketNotifyEmail(self.env)
            tn.notify(ticket, newticket=True)
            message = notifysuite.smtpd.get_message()
            headers, body = parse_smtp_message(message)
            if public_cc:
                # Msg should have a To list
                self.assertIn('To', headers)
                # Extract the list of 'To' recipients from the message
                to = [rcpt.strip() for rcpt in headers['To'].split(',')]
            else:
                # Msg should not have a To list
                self.assertNotIn('To', headers)
                # Extract the list of 'To' recipients from the message
                to = []
            # Extract the list of 'Cc' recipients from the message
            cc = [rcpt.strip() for rcpt in headers['Cc'].split(',')]
            # Extract the list of the actual SMTP recipients
            rcptlist = notifysuite.smtpd.get_recipients()
            # Build the list of the expected 'Cc' recipients
            ccrcpt = self.env.config.get('notification', 'smtp_always_cc')
            cclist = [ccr.strip() for ccr in ccrcpt.split(',')]
            for rcpt in cclist:
                # Each recipient of the 'Cc' list should appear
                # in the 'Cc' header
                self.assertIn(rcpt, cc)
                # Check the message has actually been sent to the recipients
                self.assertIn(rcpt, rcptlist)
            # Build the list of the expected 'Bcc' recipients
            bccrcpt = self.env.config.get('notification', 'smtp_always_bcc')
            bcclist = [bccr.strip() for bccr in bccrcpt.split(',')]
            for rcpt in bcclist:
                # Check none of the 'Bcc' recipients appears
                # in the 'To' header
                self.assertNotIn(rcpt, to)
                # Check the message has actually been sent to the recipients
                self.assertIn(rcpt, rcptlist)
        for public in False, True:
            run_bcc_feature(public)

    def test_short_login(self):
        """Email addresses without a FQDN"""
        def _test_short_login(enabled):
            ticket = Ticket(self.env)
            ticket['reporter'] = 'joeuser'
            ticket['summary'] = 'This is a summary'
            ticket.insert()
            # Be sure that at least one email address is valid, so that we
            # send a notification even if other addresses are not valid
            self.env.config.set('notification', 'smtp_always_cc',
                                'joe.bar@example.net')
            self.env.config.set('notification', 'use_short_addr', enabled)
            tn = TicketNotifyEmail(self.env)
            tn.notify(ticket, newticket=True)
            message = notifysuite.smtpd.get_message()
            headers, body = parse_smtp_message(message)
            # Msg should not have a 'To' header
            if not enabled:
                self.assertNotIn('To', headers)
            else:
                tolist = [addr.strip() for addr in headers['To'].split(',')]
            # Msg should have a 'Cc' field
            self.assertIn('Cc', headers)
            cclist = [addr.strip() for addr in headers['Cc'].split(',')]
            if enabled:
                # Msg should be delivered to the reporter
                self.assertIn(ticket['reporter'], tolist)
            else:
                # Msg should not be delivered to joeuser
                self.assertNotIn(ticket['reporter'], cclist)
            # Msg should still be delivered to the always_cc list
            self.assertIn(self.env.config.get('notification',
                                              'smtp_always_cc'), cclist)
        # Validate with and without the short addr option enabled
        for enable in False, True:
            _test_short_login(enable)

    def test_default_domain(self):
        """Default domain name"""
        def _test_default_domain(enabled):
            self.env.config.set('notification', 'always_notify_owner',
                                'false')
            self.env.config.set('notification', 'always_notify_reporter',
                                'false')
            self.env.config.set('notification', 'smtp_always_cc', '')
            ticket = Ticket(self.env)
            ticket['cc'] = 'joenodom, joewithdom@example.com'
            ticket['summary'] = 'This is a summary'
            ticket.insert()
            # Be sure that at least one email address is valid, so that we
            # send a notification even if other addresses are not valid
            self.env.config.set('notification', 'smtp_always_cc',
                                'joe.bar@example.net')
            if enabled:
                self.env.config.set('notification', 'smtp_default_domain',
                                    'example.org')
            tn = TicketNotifyEmail(self.env)
            tn.notify(ticket, newticket=True)
            message = notifysuite.smtpd.get_message()
            headers, body = parse_smtp_message(message)
            # Msg should always have a 'Cc' field
            self.assertIn('Cc', headers)
            cclist = [addr.strip() for addr in headers['Cc'].split(',')]
            self.assertIn('joewithdom@example.com', cclist)
            self.assertIn('joe.bar@example.net', cclist)
            if enabled:
                self.assertEqual(3, len(cclist))
                self.assertIn('joenodom@example.org', cclist)
            else:
                self.assertEqual(2, len(cclist))
                self.assertNotIn('joenodom', cclist)

        # Validate with and without a default domain
        for enable in False, True:
            _test_default_domain(enable)

    def test_email_map(self):
        """Login-to-email mapping"""
        self.env.config.set('notification', 'always_notify_owner', 'true')
        self.env.config.set('notification', 'always_notify_reporter', 'true')
        self.env.config.set('notification', 'smtp_always_cc',
                            'joe@example.com')
        self.env.known_users = [('joeuser', 'Joe User',
                                 'user-joe@example.com'),
                                ('jim@domain', 'Jim User',
                                 'user-jim@example.com')]
        ticket = Ticket(self.env)
        ticket['reporter'] = 'joeuser'
        ticket['owner'] = 'jim@domain'
        ticket['summary'] = 'This is a summary'
        ticket.insert()
        tn = TicketNotifyEmail(self.env)
        tn.notify(ticket, newticket=True)
        message = notifysuite.smtpd.get_message()
        headers, body = parse_smtp_message(message)
        # Msg should always have a 'To' field
        self.assertIn('To', headers)
        tolist = [addr.strip() for addr in headers['To'].split(',')]
        # 'To' list should have been resolved to the real email address
        self.assertIn('user-joe@example.com', tolist)
        self.assertIn('user-jim@example.com', tolist)
        self.assertNotIn('joeuser', tolist)
        self.assertNotIn('jim@domain', tolist)

    def test_from_author(self):
        """Using the reporter or change author as the notification sender"""
        self.env.config.set('notification', 'smtp_from', 'trac@example.com')
        self.env.config.set('notification', 'smtp_from_name', 'My Trac')
        self.env.config.set('notification', 'smtp_from_author', 'true')
        self.env.known_users = [('joeuser', 'Joe User',
                                 'user-joe@example.com'),
                                ('jim@domain', 'Jim User',
                                 'user-jim@example.com'),
                                ('noemail', 'No e-mail', ''),
                                ('noname', '', 'user-noname@example.com')]
        # Ticket creation uses the reporter
        ticket = Ticket(self.env)
        ticket['reporter'] = 'joeuser'
        ticket['summary'] = 'This is a summary'
        ticket.insert()
        tn = TicketNotifyEmail(self.env)
        tn.notify(ticket, newticket=True)
        message = notifysuite.smtpd.get_message()
        headers, body = parse_smtp_message(message)
        self.assertEqual('"Joe User" <user-joe@example.com>', headers['From'])
        # Ticket change uses the change author
        ticket['summary'] = 'Modified summary'
        ticket.save_changes('jim@domain', 'Made some changes')
        tn = TicketNotifyEmail(self.env)
        tn.notify(ticket, newticket=False, modtime=ticket['changetime'])
        message = notifysuite.smtpd.get_message()
        headers, body = parse_smtp_message(message)
        self.assertEqual('"Jim User" <user-jim@example.com>', headers['From'])
        # Known author without name uses e-mail address only
        ticket['summary'] = 'Final summary'
        ticket.save_changes('noname', 'Final changes')
        tn = TicketNotifyEmail(self.env)
        tn.notify(ticket, newticket=False, modtime=ticket['changetime'])
        message = notifysuite.smtpd.get_message()
        headers, body = parse_smtp_message(message)
        self.assertEqual('user-noname@example.com', headers['From'])
        # Known author without e-mail uses smtp_from and smtp_from_name
        ticket['summary'] = 'Other summary'
        ticket.save_changes('noemail', 'More changes')
        tn = TicketNotifyEmail(self.env)
        tn.notify(ticket, newticket=False, modtime=ticket['changetime'])
        message = notifysuite.smtpd.get_message()
        headers, body = parse_smtp_message(message)
        self.assertEqual('"My Trac" <trac@example.com>', headers['From'])
        # Unknown author with name and e-mail address
        ticket['summary'] = 'Some summary'
        ticket.save_changes('Test User <test@example.com>', 'Some changes')
        tn = TicketNotifyEmail(self.env)
        tn.notify(ticket, newticket=False, modtime=ticket['changetime'])
        message = notifysuite.smtpd.get_message()
        headers, body = parse_smtp_message(message)
        self.assertEqual('"Test User" <test@example.com>', headers['From'])
        # Unknown author with e-mail address only
        ticket['summary'] = 'Some summary'
        ticket.save_changes('test@example.com', 'Some changes')
        tn = TicketNotifyEmail(self.env)
        tn.notify(ticket, newticket=False, modtime=ticket['changetime'])
        message = notifysuite.smtpd.get_message()
        headers, body = parse_smtp_message(message)
        self.assertEqual('test@example.com', headers['From'])
        # Unknown author uses smtp_from and smtp_from_name
        ticket['summary'] = 'Better summary'
        ticket.save_changes('unknown', 'Made more changes')
        tn = TicketNotifyEmail(self.env)
        tn.notify(ticket, newticket=False, modtime=ticket['changetime'])
        message = notifysuite.smtpd.get_message()
        headers, body = parse_smtp_message(message)
        self.assertEqual('"My Trac" <trac@example.com>', headers['From'])

    def test_ignore_domains(self):
        """Non-SMTP domain exclusion"""
        self.env.config.set('notification', 'ignore_domains',
                            'example.com, example.org')
        self.env.known_users = \
            [('kerberos@example.com', 'No Email', ''),
             ('kerberos@example.org', 'With Email', 'kerb@example.net')]
        ticket = Ticket(self.env)
        ticket['reporter'] = 'kerberos@example.com'
        ticket['owner'] = 'kerberos@example.org'
        ticket['summary'] = 'This is a summary'
        ticket.insert()
        tn = TicketNotifyEmail(self.env)
        tn.notify(ticket, newticket=True)
        message = notifysuite.smtpd.get_message()
        headers, body = parse_smtp_message(message)
        # Msg should always have a 'To' field
        self.assertIn('To', headers)
        tolist = [addr.strip() for addr in headers['To'].split(',')]
        # 'To' list should not contain addresses with non-SMTP domains
        self.assertNotIn('kerberos@example.com', tolist)
        self.assertNotIn('kerberos@example.org', tolist)
        # 'To' list should have been resolved to the actual email address
        self.assertIn('kerb@example.net', tolist)
        self.assertEqual(1, len(tolist))

    def test_admit_domains(self):
        """SMTP domain inclusion"""
        self.env.config.set('notification', 'admit_domains',
                            'localdomain, server')
        ticket = Ticket(self.env)
        ticket['reporter'] = 'joeuser@example.com'
        ticket['summary'] = 'This is a summary'
        ticket['cc'] = 'joe.user@localdomain, joe.user@unknown, ' \
                       'joe.user@server'
        ticket.insert()
        tn = TicketNotifyEmail(self.env)
        tn.notify(ticket, newticket=True)
        message = notifysuite.smtpd.get_message()
        headers, body = parse_smtp_message(message)
        # Msg should always have a 'To' field
        self.assertIn('Cc', headers)
        cclist = [addr.strip() for addr in headers['Cc'].split(',')]
        # 'Cc' list should contain addresses with SMTP included domains
        self.assertIn('joe.user@localdomain', cclist)
        self.assertIn('joe.user@server', cclist)
        # 'Cc' list should not contain non-FQDN domains
        self.assertNotIn('joe.user@unknown', cclist)
        self.assertEqual(4, len(cclist))

    def test_multiline_header(self):
        """Encoded headers split into multiple lines"""
        self.env.config.set('notification', 'mime_encoding', 'qp')
        ticket = Ticket(self.env)
        ticket['reporter'] = 'joe.user@example.org'
        # Forces non-ascii characters
        ticket['summary'] = u'A_very %s súmmäry' % u' '.join(['long'] * 20)
        ticket.insert()
        tn = TicketNotifyEmail(self.env)
        tn.notify(ticket, newticket=True)
        message = notifysuite.smtpd.get_message()
        headers, body = parse_smtp_message(message)
        # Discards the project name & ticket number
        subject = headers['Subject']
        summary = subject[subject.find(':')+2:]
        self.assertEqual(ticket['summary'], summary)

    def test_mimebody_b64(self):
        """MIME Base64/utf-8 encoding"""
        self.env.config.set('notification', 'mime_encoding', 'base64')
        ticket = Ticket(self.env)
        ticket['reporter'] = 'joe.user@example.org'
        ticket['summary'] = u'This is a long enough summary to cause Trac ' \
                            u'to generate a multi-line (2 lines) súmmäry'
        ticket.insert()
        self._validate_mimebody((base64, 'base64', 'utf-8'), ticket, True)

    def test_mimebody_qp(self):
        """MIME QP/utf-8 encoding"""
        self.env.config.set('notification', 'mime_encoding', 'qp')
        ticket = Ticket(self.env)
        ticket['reporter'] = 'joe.user@example.org'
        ticket['summary'] = u'This is a long enough summary to cause Trac ' \
                            u'to generate a multi-line (2 lines) súmmäry'
        ticket.insert()
        self._validate_mimebody((quopri, 'quoted-printable', 'utf-8'),
                                ticket, True)

    def test_mimebody_none_7bit(self):
        """MIME None encoding resulting in 7bit"""
        self.env.config.set('notification', 'mime_encoding', 'none')
        ticket = Ticket(self.env)
        ticket['reporter'] = 'joe.user'
        ticket['summary'] = u'This is a summary'
        ticket.insert()
        self._validate_mimebody((None, '7bit', 'utf-8'), ticket, True)

    def test_mimebody_none_8bit(self):
        """MIME None encoding resulting in 8bit"""
        self.env.config.set('notification', 'mime_encoding', 'none')
        ticket = Ticket(self.env)
        ticket['reporter'] = 'joe.user'
        ticket['summary'] = u'This is a summary for Jöe Usèr'
        ticket.insert()
        self._validate_mimebody((None, '8bit', 'utf-8'), ticket, True)

    def test_md5_digest(self):
        """MD5 digest w/ non-ASCII recipient address (#3491)"""
        self.env.config.set('notification', 'always_notify_owner', 'false')
        self.env.config.set('notification', 'always_notify_reporter', 'true')
        self.env.config.set('notification', 'smtp_always_cc', '')
        ticket = Ticket(self.env)
        ticket['reporter'] = u'"Jöe Usèr" <joe.user@example.org>'
        ticket['summary'] = u'This is a summary'
        ticket.insert()
        tn = TicketNotifyEmail(self.env)
        tn.notify(ticket, newticket=True)
        message = notifysuite.smtpd.get_message()
        headers, body = parse_smtp_message(message)
        self.assertEqual('joe.user@example.org', headers['To'])

    def test_previous_cc_list(self):
        """Members removed from CC list receive notifications"""
        ticket = Ticket(self.env)
        ticket['summary'] = 'Foo'
        ticket['cc'] = 'joe.user1@example.net'
        ticket.insert()
        ticket['cc'] = 'joe.user2@example.net'
        now = datetime.now(utc)
        ticket.save_changes('joe.bar@example.com', 'Removed from cc', now)
        tn = TicketNotifyEmail(self.env)
        tn.notify(ticket, newticket=False, modtime=now)
        recipients = notifysuite.smtpd.get_recipients()
        self.assertIn('joe.user1@example.net', recipients)
        self.assertIn('joe.user2@example.net', recipients)

    def test_previous_owner(self):
        """Previous owner is notified when ticket is reassigned (#2311)
           if always_notify_owner is set to True"""
        def _test_owner(enabled):
            self.env.config.set('notification', 'always_notify_owner', enabled)
            ticket = Ticket(self.env)
            ticket['summary'] = 'Foo'
            ticket['owner'] = prev_owner = 'joe.user1@example.net'
            ticket.insert()
            ticket['owner'] = new_owner = 'joe.user2@example.net'
            now = datetime.now(utc)
            ticket.save_changes('joe.bar@example.com', 'Changed owner', now)
            tn = TicketNotifyEmail(self.env)
            tn.notify(ticket, newticket=False, modtime=now)
            recipients = notifysuite.smtpd.get_recipients()
            if enabled:
                self.assertIn(prev_owner, recipients)
                self.assertIn(new_owner, recipients)
            else:
                self.assertNotIn(prev_owner, recipients)
                self.assertNotIn(new_owner, recipients)

        for enable in False, True:
            _test_owner(enable)

    def _validate_mimebody(self, mime, ticket, newtk):
        """Body of a ticket notification message"""
        mime_decoder, mime_name, mime_charset = mime
        tn = TicketNotifyEmail(self.env)
        tn.notify(ticket, newticket=newtk)
        message = notifysuite.smtpd.get_message()
        headers, body = parse_smtp_message(message)
        self.assertIn('MIME-Version', headers)
        self.assertIn('Content-Type', headers)
        self.assertIn('Content-Transfer-Encoding', headers)
        self.assertTrue(re.compile(r"1.\d").match(headers['MIME-Version']))
        type_re = re.compile(r'^text/plain;\scharset="([\w\-\d]+)"$')
        charset = type_re.match(headers['Content-Type'])
        self.assertTrue(charset)
        charset = charset.group(1)
        self.assertEqual(mime_charset, charset)
        self.assertEqual(headers['Content-Transfer-Encoding'], mime_name)
        # checks the width of each body line
        for line in body.splitlines():
            self.assertTrue(len(line) <= MAXBODYWIDTH)
        # attempts to decode the body, following the specified MIME encoding
        # and charset
        try:
            if mime_decoder:
                body = mime_decoder.decodestring(body)
            body = unicode(body, charset)
        except Exception, e:
            raise AssertionError(e)
        # now processes each line of the body
        bodylines = body.splitlines()
        # body starts with one of more summary lines, first line is prefixed
        # with the ticket number such as #<n>: summary
        # finds the banner after the summary
        banner_delim_re = re.compile(r'^\-+\+\-+$')
        bodyheader = []
        while not banner_delim_re.match(bodylines[0]):
            bodyheader.append(bodylines.pop(0))
        # summary should be present
        self.assertTrue(bodyheader)
        # banner should not be empty
        self.assertTrue(bodylines)
        # extracts the ticket ID from the first line
        tknum, bodyheader[0] = bodyheader[0].split(' ', 1)
        self.assertEqual('#', tknum[0])
        try:
            tkid = int(tknum[1:-1])
            self.assertEqual(1, tkid)
        except ValueError:
            raise AssertionError("invalid ticket number")
        self.assertEqual(':', tknum[-1])
        summary = ' '.join(bodyheader)
        self.assertEqual(summary, ticket['summary'])
        # now checks the banner contents
        self.assertTrue(banner_delim_re.match(bodylines[0]))
        banner = True
        footer = None
        props = {}
        for line in bodylines[1:]:
            # detect end of banner
            if banner_delim_re.match(line):
                banner = False
                continue
            if banner:
                # parse banner and fill in a property dict
                properties = line.split('|')
                self.assertEqual(2, len(properties))
                for prop in properties:
                    if prop.strip() == '':
                        continue
                    k, v = prop.split(':')
                    props[k.strip().lower()] = v.strip()
            # detect footer marker (weak detection)
            if not footer:
                if line.strip() == '--':
                    footer = 0
                    continue
            # check footer
            if footer is not None:
                footer += 1
                # invalid footer detection
                self.assertTrue(footer <= 3)
                # check ticket link
                if line[:11] == 'Ticket URL:':
                    ticket_link = self.env.abs_href.ticket(ticket.id)
                    self.assertEqual(line[12:].strip(), "<%s>" % ticket_link)
                # note project title / URL are not validated yet

        # ticket properties which are not expected in the banner
        xlist = ['summary', 'description', 'comment', 'time', 'changetime']
        # check banner content (field exists, msg value matches ticket value)
        for p in [prop for prop in ticket.values.keys() if prop not in xlist]:
            self.assertIn(p, props)
            # Email addresses might be obfuscated
            if '@' in ticket[p] and '@' in props[p]:
                self.assertEqual(props[p].split('@')[0],
                                 ticket[p].split('@')[0])
            else:
                self.assertEqual(props[p], ticket[p])

    def test_props_format_ambiwidth_single(self):
        self.env.config.set('notification', 'mime_encoding', 'none')
        self.env.config.set('notification', 'ambiguous_char_width', '')
        ticket = Ticket(self.env)
        ticket['summary'] = u'This is a summary'
        ticket['reporter'] = u'аnonymoиs'
        ticket['status'] = u'new'
        ticket['owner'] = u'somеbody'
        ticket['type'] = u'バグ(dеfеct)'
        ticket['priority'] = u'メジャー(mаjor)'
        ticket['milestone'] = u'マイルストーン1'
        ticket['component'] = u'コンポーネント1'
        ticket['version'] = u'2.0 аlphа'
        ticket['resolution'] = u'fixed'
        ticket['keywords'] = u''
        ticket.insert()
        formatted = """\
  Reporter:  аnonymoиs        |      Owner:  somеbody
      Type:  バグ(dеfеct)     |     Status:  new
  Priority:  メジャー(mаjor)  |  Milestone:  マイルストーン1
 Component:  コンポーネント1  |    Version:  2.0 аlphа
Resolution:  fixed            |   Keywords:"""
        self._validate_props_format(formatted, ticket)

    def test_props_format_ambiwidth_double(self):
        self.env.config.set('notification', 'mime_encoding', 'none')
        self.env.config.set('notification', 'ambiguous_char_width', 'double')
        ticket = Ticket(self.env)
        ticket['summary'] = u'This is a summary'
        ticket['reporter'] = u'аnonymoиs'
        ticket['status'] = u'new'
        ticket['owner'] = u'somеbody'
        ticket['type'] = u'バグ(dеfеct)'
        ticket['priority'] = u'メジャー(mаjor)'
        ticket['milestone'] = u'マイルストーン1'
        ticket['component'] = u'コンポーネント1'
        ticket['version'] = u'2.0 аlphа'
        ticket['resolution'] = u'fixed'
        ticket['keywords'] = u''
        ticket.insert()
        formatted = """\
  Reporter:  аnonymoиs       |      Owner:  somеbody
      Type:  バグ(dеfеct)    |     Status:  new
  Priority:  メジャー(mаjor)  |  Milestone:  マイルストーン1
 Component:  コンポーネント1   |    Version:  2.0 аlphа
Resolution:  fixed             |   Keywords:"""
        self._validate_props_format(formatted, ticket)

    def test_props_format_obfuscated_email(self):
        self.env.config.set('notification', 'mime_encoding', 'none')
        ticket = Ticket(self.env)
        ticket['summary'] = u'This is a summary'
        ticket['reporter'] = u'joe@foobar.foo.bar.example.org'
        ticket['status'] = u'new'
        ticket['owner'] = u'joe.bar@foobar.foo.bar.example.org'
        ticket['type'] = u'defect'
        ticket['priority'] = u'major'
        ticket['milestone'] = u'milestone1'
        ticket['component'] = u'component1'
        ticket['version'] = u'2.0'
        ticket['resolution'] = u'fixed'
        ticket['keywords'] = u''
        ticket.insert()
        formatted = """\
  Reporter:  joe@…       |      Owner:  joe.bar@…
      Type:  defect      |     Status:  new
  Priority:  major       |  Milestone:  milestone1
 Component:  component1  |    Version:  2.0
Resolution:  fixed       |   Keywords:"""
        self._validate_props_format(formatted, ticket)

    def test_props_format_obfuscated_email_disabled(self):
        self.env.config.set('notification', 'mime_encoding', 'none')
        self.env.config.set('trac', 'show_email_addresses', 'true')
        ticket = Ticket(self.env)
        ticket['summary'] = u'This is a summary'
        ticket['reporter'] = u'joe@foobar.foo.bar.example.org'
        ticket['status'] = u'new'
        ticket['owner'] = u'joe.bar@foobar.foo.bar.example.org'
        ticket['type'] = u'defect'
        ticket['priority'] = u'major'
        ticket['milestone'] = u'milestone1'
        ticket['component'] = u'component1'
        ticket['version'] = u'2.0'
        ticket['resolution'] = u'fixed'
        ticket['keywords'] = u''
        ticket.insert()
        formatted = """\
  Reporter:                          |      Owner:
  joe@foobar.foo.bar.example.org     |  joe.bar@foobar.foo.bar.example.org
      Type:  defect                  |     Status:  new
  Priority:  major                   |  Milestone:  milestone1
 Component:  component1              |    Version:  2.0
Resolution:  fixed                   |   Keywords:"""
        self._validate_props_format(formatted, ticket)

    def test_props_format_wrap_leftside(self):
        self.env.config.set('notification', 'mime_encoding', 'none')
        ticket = Ticket(self.env)
        ticket['summary'] = u'This is a summary'
        ticket['reporter'] = u'anonymous'
        ticket['status'] = u'new'
        ticket['owner'] = u'somebody'
        ticket['type'] = u'defect'
        ticket['priority'] = u'major'
        ticket['milestone'] = u'milestone1'
        ticket['component'] = u'Lorem ipsum dolor sit amet, consectetur ' \
                              u'adipisicing elit, sed do eiusmod tempor ' \
                              u'incididunt ut labore et dolore magna ' \
                              u'aliqua. Ut enim ad minim veniam, quis ' \
                              u'nostrud exercitation ullamco laboris nisi ' \
                              u'ut aliquip ex ea commodo consequat. Duis ' \
                              u'aute irure dolor in reprehenderit in ' \
                              u'voluptate velit esse cillum dolore eu ' \
                              u'fugiat nulla pariatur. Excepteur sint ' \
                              u'occaecat cupidatat non proident, sunt in ' \
                              u'culpa qui officia deserunt mollit anim id ' \
                              u'est laborum.'
        ticket['version'] = u'2.0'
        ticket['resolution'] = u'fixed'
        ticket['keywords'] = u''
        ticket.insert()
        formatted = """\
  Reporter:  anonymous                           |      Owner:  somebody
      Type:  defect                              |     Status:  new
  Priority:  major                               |  Milestone:  milestone1
 Component:  Lorem ipsum dolor sit amet,         |    Version:  2.0
  consectetur adipisicing elit, sed do eiusmod   |
  tempor incididunt ut labore et dolore magna    |
  aliqua. Ut enim ad minim veniam, quis nostrud  |
  exercitation ullamco laboris nisi ut aliquip   |
  ex ea commodo consequat. Duis aute irure       |
  dolor in reprehenderit in voluptate velit      |
  esse cillum dolore eu fugiat nulla pariatur.   |
  Excepteur sint occaecat cupidatat non          |
  proident, sunt in culpa qui officia deserunt   |
  mollit anim id est laborum.                    |
Resolution:  fixed                               |   Keywords:"""
        self._validate_props_format(formatted, ticket)

    def test_props_format_wrap_leftside_unicode(self):
        self.env.config.set('notification', 'mime_encoding', 'none')
        ticket = Ticket(self.env)
        ticket['summary'] = u'This is a summary'
        ticket['reporter'] = u'anonymous'
        ticket['status'] = u'new'
        ticket['owner'] = u'somebody'
        ticket['type'] = u'defect'
        ticket['priority'] = u'major'
        ticket['milestone'] = u'milestone1'
        ticket['component'] = u'Trac は BSD ライセンスのもとで配' \
                              u'布されています。[1:]このライセ' \
                              u'ンスの全文は、配布ファイルに' \
                              u'含まれている [3:COPYING] ファイル' \
                              u'と同じものが[2:オンライン]で参' \
                              u'照できます。'
        ticket['version'] = u'2.0'
        ticket['resolution'] = u'fixed'
        ticket['keywords'] = u''
        ticket.insert()
        formatted = """\
  Reporter:  anonymous                           |      Owner:  somebody
      Type:  defect                              |     Status:  new
  Priority:  major                               |  Milestone:  milestone1
 Component:  Trac は BSD ライセンスのもとで配布  |    Version:  2.0
  されています。[1:]このライセンスの全文は、配   |
  布ファイルに含まれている [3:COPYING] ファイル  |
  と同じものが[2:オンライン]で参照できます。     |
Resolution:  fixed                               |   Keywords:"""
        self._validate_props_format(formatted, ticket)

    def test_props_format_wrap_rightside(self):
        self.env.config.set('notification', 'mime_encoding', 'none')
        ticket = Ticket(self.env)
        ticket['summary'] = u'This is a summary'
        ticket['reporter'] = u'anonymous'
        ticket['status'] = u'new'
        ticket['owner'] = u'somebody'
        ticket['type'] = u'defect'
        ticket['priority'] = u'major'
        ticket['milestone'] = u'Lorem ipsum dolor sit amet, consectetur ' \
                              u'adipisicing elit, sed do eiusmod tempor ' \
                              u'incididunt ut labore et dolore magna ' \
                              u'aliqua. Ut enim ad minim veniam, quis ' \
                              u'nostrud exercitation ullamco laboris nisi ' \
                              u'ut aliquip ex ea commodo consequat. Duis ' \
                              u'aute irure dolor in reprehenderit in ' \
                              u'voluptate velit esse cillum dolore eu ' \
                              u'fugiat nulla pariatur. Excepteur sint ' \
                              u'occaecat cupidatat non proident, sunt in ' \
                              u'culpa qui officia deserunt mollit anim id ' \
                              u'est laborum.'
        ticket['component'] = u'component1'
        ticket['version'] = u'2.0 Standard and International Edition'
        ticket['resolution'] = u'fixed'
        ticket['keywords'] = u''
        ticket.insert()
        formatted = """\
  Reporter:  anonymous   |      Owner:  somebody
      Type:  defect      |     Status:  new
  Priority:  major       |  Milestone:  Lorem ipsum dolor sit amet,
                         |  consectetur adipisicing elit, sed do eiusmod
                         |  tempor incididunt ut labore et dolore magna
                         |  aliqua. Ut enim ad minim veniam, quis nostrud
                         |  exercitation ullamco laboris nisi ut aliquip ex
                         |  ea commodo consequat. Duis aute irure dolor in
                         |  reprehenderit in voluptate velit esse cillum
                         |  dolore eu fugiat nulla pariatur. Excepteur sint
                         |  occaecat cupidatat non proident, sunt in culpa
                         |  qui officia deserunt mollit anim id est
                         |  laborum.
 Component:  component1  |    Version:  2.0 Standard and International
                         |  Edition
Resolution:  fixed       |   Keywords:"""
        self._validate_props_format(formatted, ticket)

    def test_props_format_wrap_rightside_unicode(self):
        self.env.config.set('notification', 'mime_encoding', 'none')
        ticket = Ticket(self.env)
        ticket['summary'] = u'This is a summary'
        ticket['reporter'] = u'anonymous'
        ticket['status'] = u'new'
        ticket['owner'] = u'somebody'
        ticket['type'] = u'defect'
        ticket['priority'] = u'major'
        ticket['milestone'] = u'Trac 在经过修改的BSD协议下发布。' \
                              u'[1:]协议的完整文本可以[2:在线查' \
                              u'看]也可在发布版的 [3:COPYING] 文' \
                              u'件中找到。'
        ticket['component'] = u'component1'
        ticket['version'] = u'2.0'
        ticket['resolution'] = u'fixed'
        ticket['keywords'] = u''
        ticket.insert()
        formatted = """\
  Reporter:  anonymous   |      Owner:  somebody
      Type:  defect      |     Status:  new
  Priority:  major       |  Milestone:  Trac 在经过修改的BSD协议下发布。
                         |  [1:]协议的完整文本可以[2:在线查看]也可在发布版
                         |  的 [3:COPYING] 文件中找到。
 Component:  component1  |    Version:  2.0
Resolution:  fixed       |   Keywords:"""
        self._validate_props_format(formatted, ticket)

    def test_props_format_wrap_bothsides(self):
        self.env.config.set('notification', 'mime_encoding', 'none')
        ticket = Ticket(self.env)
        ticket['summary'] = u'This is a summary'
        ticket['reporter'] = u'anonymous'
        ticket['status'] = u'new'
        ticket['owner'] = u'somebody'
        ticket['type'] = u'defect'
        ticket['priority'] = u'major'
        ticket['milestone'] = u'Lorem ipsum dolor sit amet, consectetur ' \
                              u'adipisicing elit, sed do eiusmod tempor ' \
                              u'incididunt ut labore et dolore magna ' \
                              u'aliqua. Ut enim ad minim veniam, quis ' \
                              u'nostrud exercitation ullamco laboris nisi ' \
                              u'ut aliquip ex ea commodo consequat. Duis ' \
                              u'aute irure dolor in reprehenderit in ' \
                              u'voluptate velit esse cillum dolore eu ' \
                              u'fugiat nulla pariatur. Excepteur sint ' \
                              u'occaecat cupidatat non proident, sunt in ' \
                              u'culpa qui officia deserunt mollit anim id ' \
                              u'est laborum.'
        ticket['component'] = (u'Lorem ipsum dolor sit amet, consectetur '
                               u'adipisicing elit, sed do eiusmod tempor '
                               u'incididunt ut labore et dolore magna aliqua.')
        ticket['version'] = u'2.0'
        ticket['resolution'] = u'fixed'
        ticket['keywords'] = u'Ut enim ad minim veniam, ....'
        ticket.insert()
        formatted = """\
  Reporter:  anonymous               |      Owner:  somebody
      Type:  defect                  |     Status:  new
  Priority:  major                   |  Milestone:  Lorem ipsum dolor sit
                                     |  amet, consectetur adipisicing elit,
                                     |  sed do eiusmod tempor incididunt ut
                                     |  labore et dolore magna aliqua. Ut
                                     |  enim ad minim veniam, quis nostrud
                                     |  exercitation ullamco laboris nisi
                                     |  ut aliquip ex ea commodo consequat.
                                     |  Duis aute irure dolor in
                                     |  reprehenderit in voluptate velit
                                     |  esse cillum dolore eu fugiat nulla
 Component:  Lorem ipsum dolor sit   |  pariatur. Excepteur sint occaecat
  amet, consectetur adipisicing      |  cupidatat non proident, sunt in
  elit, sed do eiusmod tempor        |  culpa qui officia deserunt mollit
  incididunt ut labore et dolore     |  anim id est laborum.
  magna aliqua.                      |    Version:  2.0
Resolution:  fixed                   |   Keywords:  Ut enim ad minim
                                     |  veniam, ...."""
        self._validate_props_format(formatted, ticket)

    def test_props_format_wrap_bothsides_unicode(self):
        self.env.config.set('notification', 'mime_encoding', 'none')
        self.env.config.set('notification', 'ambiguous_char_width', 'double')
        ticket = Ticket(self.env)
        ticket['summary'] = u'This is a summary'
        ticket['reporter'] = u'anonymous'
        ticket['status'] = u'new'
        ticket['owner'] = u'somebody'
        ticket['type'] = u'defect'
        ticket['priority'] = u'major'
        ticket['milestone'] = u'Trac 在经过修改的BSD协议下发布。' \
                              u'[1:]协议的完整文本可以[2:在线查' \
                              u'看]也可在发布版的 [3:COPYING] 文' \
                              u'件中找到。'
        ticket['component'] = u'Trac は BSD ライセンスのもとで配' \
                              u'布されています。[1:]このライセ' \
                              u'ンスの全文は、※配布ファイル' \
                              u'に含まれている[3:CОPYING]ファイ' \
                              u'ルと同じものが[2:オンライン]で' \
                              u'参照できます。'
        ticket['version'] = u'2.0 International Edition'
        ticket['resolution'] = u'fixed'
        ticket['keywords'] = u''
        ticket.insert()
        formatted = """\
  Reporter:  anonymous               |      Owner:  somebody
      Type:  defect                  |     Status:  new
  Priority:  major                   |  Milestone:  Trac 在经过修改的BSD协
 Component:  Trac は BSD ライセンス  |  议下发布。[1:]协议的完整文本可以[2:
  のもとで配布されています。[1:]こ   |  在线查看]也可在发布版的 [3:COPYING]
  のライセンスの全文は、※配布ファ   |  文件中找到。
  イルに含まれている[3:CОPYING]フ   |    Version:  2.0 International
  ァイルと同じものが[2:オンライン]   |  Edition
  で参照できます。                   |
Resolution:  fixed                   |   Keywords:"""
        self._validate_props_format(formatted, ticket)

    def test_props_format_wrap_ticket_10283(self):
        self.env.config.set('notification', 'mime_encoding', 'none')
        for name, value in (('blockedby', 'text'),
                            ('blockedby.label', 'Blocked by'),
                            ('blockedby.order', '6'),
                            ('blocking', 'text'),
                            ('blocking.label', 'Blocking'),
                            ('blocking.order', '5'),
                            ('deployment', 'text'),
                            ('deployment.label', 'Deployment state'),
                            ('deployment.order', '1'),
                            ('nodes', 'text'),
                            ('nodes.label', 'Related nodes'),
                            ('nodes.order', '3'),
                            ('privacy', 'text'),
                            ('privacy.label', 'Privacy sensitive'),
                            ('privacy.order', '2'),
                            ('sensitive', 'text'),
                            ('sensitive.label', 'Security sensitive'),
                            ('sensitive.order', '4')):
            self.env.config.set('ticket-custom', name, value)

        ticket = Ticket(self.env)
        ticket['summary'] = u'This is a summary'
        ticket['reporter'] = u'anonymous'
        ticket['owner'] = u'somebody'
        ticket['type'] = u'defect'
        ticket['status'] = u'closed'
        ticket['priority'] = u'normal'
        ticket['milestone'] = u'iter_01'
        ticket['component'] = u'XXXXXXXXXXXXXXXXXXXXXXXXXX'
        ticket['resolution'] = u'fixed'
        ticket['keywords'] = u''
        ticket['deployment'] = ''
        ticket['privacy'] = '0'
        ticket['nodes'] = 'XXXXXXXXXX'
        ticket['sensitive'] = '0'
        ticket['blocking'] = ''
        ticket['blockedby'] = ''
        ticket.insert()

        formatted = """\
          Reporter:  anonymous                   |             Owner:
                                                 |  somebody
              Type:  defect                      |            Status:
                                                 |  closed
          Priority:  normal                      |         Milestone:
                                                 |  iter_01
         Component:  XXXXXXXXXXXXXXXXXXXXXXXXXX  |        Resolution:
                                                 |  fixed
          Keywords:                              |  Deployment state:
 Privacy sensitive:  0                           |     Related nodes:
                                                 |  XXXXXXXXXX
Security sensitive:  0                           |          Blocking:
        Blocked by:                              |"""
        self._validate_props_format(formatted, ticket)

    def _validate_props_format(self, expected, ticket):
        tn = TicketNotifyEmail(self.env)
        tn.notify(ticket, newticket=True)
        message = notifysuite.smtpd.get_message()
        headers, body = parse_smtp_message(message)
        bodylines = body.splitlines()
        # Extract ticket properties
        delim_re = re.compile(r'^\-+\+\-+$')
        while not delim_re.match(bodylines[0]):
            bodylines.pop(0)
        lines = []
        for line in bodylines[1:]:
            if delim_re.match(line):
                break
            lines.append(line)
        self.assertEqual(expected, '\n'.join(lines))

    def test_notification_does_not_alter_ticket_instance(self):
        ticket = Ticket(self.env)
        ticket['summary'] = 'My Summary'
        ticket['description'] = 'Some description'
        ticket.insert()
        tn = TicketNotifyEmail(self.env)
        tn.notify(ticket, newticket=True)
        self.assertIsNotNone(notifysuite.smtpd.get_message())
        self.assertEqual('My Summary', ticket['summary'])
        self.assertEqual('Some description', ticket['description'])
        valid_fieldnames = set([f['name'] for f in ticket.fields])
        current_fieldnames = set(ticket.values.keys())
        self.assertEqual(set(), current_fieldnames - valid_fieldnames)

    def test_notification_get_message_id_unicode(self):
        ticket = Ticket(self.env)
        ticket['summary'] = 'My Summary'
        ticket['description'] = 'Some description'
        ticket.insert()
        self.env.config.set('project', 'url', u"пиво Müller ")
        tn = TicketNotifyEmail(self.env)
        tn.ticket = ticket
        tn.get_message_id('foo')

    def test_mime_meta_characters_in_from_header(self):
        """MIME encoding with meta characters in From header"""

        self.env.config.set('notification', 'smtp_from', 'trac@example.com')
        self.env.config.set('notification', 'mime_encoding', 'base64')
        ticket = Ticket(self.env)
        ticket['reporter'] = 'joeuser'
        ticket['summary'] = 'This is a summary'
        ticket.insert()
        tn = TicketNotifyEmail(self.env)

        def notify(from_name):
            self.env.config.set('notification', 'smtp_from_name', from_name)
            tn.notify(ticket, newticket=True)
            message = notifysuite.smtpd.get_message()
            headers, body = parse_smtp_message(message)
            return message, headers, body

        message, headers, body = notify(u'Träc')
        self.assertEqual(r'"=?utf-8?b?VHLDpGM=?=" <trac@example.com>',
                         headers['From'])
        message, headers, body = notify(u'Trac\\')
        self.assertEqual(r'"Trac\\" <trac@example.com>', headers['From'])
        message, headers, body = notify(u'Trac"')
        self.assertEqual(r'"Trac\"" <trac@example.com>', headers['From'])
        message, headers, body = notify(u'=?utf-8?b?****?=')
        self.assertEqual('"=?utf-8?b?PT91dGYtOD9iPyoqKio/PQ==?=" '
                         '<trac@example.com>', headers['From'])

    def test_mime_meta_characters_in_subject_header(self):
        """MIME encoding with meta characters in Subject header"""

        self.env.config.set('notification', 'smtp_from', 'trac@example.com')
        self.env.config.set('notification', 'mime_encoding', 'base64')
        summary = u'=?utf-8?q?****?='
        ticket = Ticket(self.env)
        ticket['reporter'] = 'joeuser'
        ticket['summary'] = summary
        ticket.insert()
        tn = TicketNotifyEmail(self.env)
        tn.notify(ticket, newticket=True)
        message = notifysuite.smtpd.get_message()
        headers, body = parse_smtp_message(message)
        self.assertIn('\nSubject: =?utf-8?b?', message)  # is mime-encoded
        self.assertEqual(summary,
                         re.split(r' #[0-9]+: ', headers['Subject'], 1)[1])


class AttachmentNotificationTestCase(unittest.TestCase):

    def setUp(self):
        self.env = EnvironmentStub(default_data=True,
                                   path=tempfile.mkdtemp(prefix='trac-tempenv-'))
        self.env.config.set('project', 'name', 'TracTest')
        self.env.config.set('notification', 'smtp_enabled', 'true')
        self.env.config.set('notification', 'smtp_port', str(SMTP_TEST_PORT))

        ticket = Ticket(self.env)
        ticket['summary'] = 'Ticket summary'
        ticket['reporter'] = 'user@domain.org'
        ticket.insert()
        self.attachment = Attachment(self.env, 'ticket', ticket.id)
        self.attachment.description = "The attachment description"
        self.attachment.author = 'user@example.com'

    def tearDown(self):
        """Signal the notification test suite that a test is over"""
        notifysuite.tear_down()
        self.env.reset_db()
        shutil.rmtree(self.env.path)

    def test_ticket_notify_attachment_enabled_attachment_added(self):
        self.attachment.insert('foo.txt', StringIO(''), 1)

        message = notifysuite.smtpd.get_message()
        headers, body = parse_smtp_message(message)

        self.assertIn("Re: [TracTest] #1: Ticket summary", headers['Subject'])
        self.assertIn(" * Attachment \"foo.txt\" added", body)
        self.assertIn("The attachment description", body)

    def test_ticket_notify_attachment_enabled_attachment_removed(self):
        self.attachment.insert('foo.txt', StringIO(''), 1)
        self.attachment.delete()

        message = notifysuite.smtpd.get_message()
        headers, body = parse_smtp_message(message)

        self.assertIn("Re: [TracTest] #1: Ticket summary", headers['Subject'])
        self.assertIn(" * Attachment \"foo.txt\" removed", body)
        self.assertIn("The attachment description", body)

    def test_author_is_obfuscated(self):
        self.env.config.set('trac', 'show_email_addresses', False)
        self.attachment.insert('foo.txt', StringIO(''), 1)

        message = notifysuite.smtpd.get_message()

        self.assertIn('Changes (by user@…)', message)

    def test_author_is_not_obfuscated(self):
        self.env.config.set('trac', 'show_email_addresses', True)
        self.attachment.insert('foo.txt', StringIO(''), 1)

        message = notifysuite.smtpd.get_message()

        self.assertIn('Changes (by user@example.com)', message)


class NotificationTestSuite(unittest.TestSuite):
    """Thin test suite wrapper to start and stop the SMTP test server"""

    def __init__(self):
        """Start the local SMTP test server"""
        unittest.TestSuite.__init__(self)
        self.smtpd = SMTPThreadedServer(SMTP_TEST_PORT)
        self.smtpd.start()
        self.addTest(unittest.makeSuite(RecipientTestCase))
        self.addTest(unittest.makeSuite(NotificationTestCase))
        self.addTest(unittest.makeSuite(AttachmentNotificationTestCase))
        self.remaining = self.countTestCases()

    def tear_down(self):
        """Reset the local SMTP test server"""
        self.smtpd.cleanup()
        self.remaining -= 1
        if self.remaining > 0:
            return
        # stop the SMTP test server when all tests have been completed
        self.smtpd.stop()


def suite():
    global notifysuite
    if not notifysuite:
        notifysuite = NotificationTestSuite()
    return notifysuite

if __name__ == '__main__':
    unittest.main(defaultTest='suite')
