import re

from trac.config import Option
from trac.core import *
from trac.resource import ResourceNotFound
from trac.ticket.api import IMilestoneChangeListener
from trac.ticket.model import Version

revision = "$Rev: 9001 $"
url = "$URL: https://svn.edgewall.org/repos/trac/trunk/sample-plugins/milestone_to_version.py $"


class MilestoneToVersion(Component):
    """Automatically create a version when a milestone is completed.

    Sample plugin demonstrating the IMilestoneChangeListener interface.
    Creates a version from a just-completed milestone based on whether the
    milestone's name matches a specified pattern.
    """

    implements(IMilestoneChangeListener)

    pattern = Option('milestone_to_version', 'pattern',
                     r'(?i)(?:v(?:er)?\.?|version)?\s*(?P<version>\d.*)',
        """A regular expression to match the names of milestones that should be
        made into versions when they are completed. The pattern must include
        one named group called 'version' that matches the version number
        itself.""")

    def milestone_created(self, milestone):
        pass

    def milestone_changed(self, milestone, old_values):
        if not milestone.is_completed or 'completed' not in old_values \
                or old_values['completed'] is not None:
            return
        m = re.match(self.pattern, milestone.name)
        if not m:
            return
        version_name = m.groupdict().get('version')
        if not version_name:
            return
        try:
            version = Version(self.env, version_name)
            if not version.time:
                version.time = milestone.completed
                version.update()
                self.log.info('Existing version "%s" updated with completion '
                              'time from milestone "%s"' %
                              (version.name, milestone.name))
            else:
                self.log.info('Version "%s" already exists.  No new version '
                              'created from milestone "%s"' %
                              (version.name, milestone.name))
        except ResourceNotFound:
            version = Version(self.env)
            version.name = version_name
            version.time = milestone.completed
            version.insert()             
            self.log.info('New version "%s" created from completed milstone '
                          '"%s".' % (version.name, milestone.name))

    def milestone_deleted(self, milestone):
        pass
