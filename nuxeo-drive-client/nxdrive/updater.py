"""Application update utilities using esky"""

import sys
import errno
import json
from urlparse import urljoin
from urllib2 import URLError
from urllib2 import HTTPError
from esky import Esky
from esky.errors import EskyBrokenError
from nxdrive.utils import version_compare
from nxdrive.logging_config import get_logger

log = get_logger(__name__)

# Update statuses
UPDATE_STATUS_UPGRADE_NEEDED = 'upgrade_needed'
UPDATE_STATUS_DOWNGRADE_NEEDED = 'downgrade_needed'
UPDATE_STATUS_UPDATE_AVAILABLE = 'update_available'
UPDATE_STATUS_UP_TO_DATE = 'up_to_date'
UPDATE_STATUS_UNAVAILABLE_SITE = 'unavailable_site'
UPDATE_STATUS_MISSING_INFO = 'missing_info'
UPDATE_STATUS_MISSING_VERSION = 'missing_version'

# Update status messages
UPDATE_STATUS_LABEL = {
    UPDATE_STATUS_UPGRADE_NEEDED: 'Upgrade required',
    UPDATE_STATUS_DOWNGRADE_NEEDED: 'Downgrade required',
    UPDATE_STATUS_UPDATE_AVAILABLE: 'Update Nuxeo Drive',
    UPDATE_STATUS_UP_TO_DATE: 'Up-to-date',
    UPDATE_STATUS_UNAVAILABLE_SITE: 'Update site unavailable',
    UPDATE_STATUS_MISSING_INFO: 'Update information unavailable',
    UPDATE_STATUS_MISSING_VERSION: 'No compatible version available',
}


class AppNotFrozen(Exception):
    pass


class UpdaterInitError(Exception):
    pass


class UnavailableUpdateSite(Exception):
    pass


class MissingUpdateSiteInfo(Exception):
    pass


class MissingCompatibleVersion(Exception):
    pass


class UpdateError(Exception):
    pass


class RootPrivilegeRequired(Exception):
    pass


class AppUpdater:
    """Class for updating a frozen application.

    Basically an Esky wrapper.
    """

    def __init__(self, version_finder=None, esky_app=None,
                 local_update_site=False):

        if esky_app is not None:
            self.esky_app = esky_app
        elif not hasattr(sys, 'frozen'):
            raise AppNotFrozen("Application is not frozen, cannot build Esky"
                               " instance, as a consequence update features"
                               " won't be available")
        elif version_finder is None:
            raise UpdaterInitError("Cannot initialize Esky instance with no"
                                   " version finder, as a consequence update"
                                   " features won't be available")
        else:
            try:
                executable = sys.executable
                log.debug("Application is frozen, building Esky instance from"
                          " executable %s and version finder %s",
                          executable, version_finder)
                self.esky_app = Esky(executable, version_finder=version_finder)
            except EskyBrokenError as e:
                log.error(e, exc_info=True)
                raise UpdaterInitError("Error initializing Esky instance, as a"
                                       " consequence update features won't be"
                                       " available")
        self.local_update_site = local_update_site
        self.update_site = self.esky_app.version_finder.download_url
        if not self.local_update_site and not self.update_site.endswith('/'):
            self.update_site = self.update_site + '/'

    def set_version_finder(self, version_finder):
        self.esky_app._set_version_finder(version_finder)

    def get_active_version(self):
        return self.esky_app.active_version

    def get_current_latest_version(self):
        return self.esky_app.version

    def find_versions(self):
        return sorted(self.esky_app.version_finder.find_versions(
                                        self.esky_app), cmp=version_compare)

    def get_server_min_version(self, client_version):
        info_file = client_version + '.json'
        missing_msg = (
            "Missing or invalid file '%s' in update site '%s', can't get"
            " server minimum version for client version %s" % (
                                info_file, self.update_site, client_version))
        try:
            if not self.local_update_site:
                url = urljoin(self.update_site, info_file)
            else:
                url = info_file
            info = self.esky_app.version_finder.open_url(url)
            version = json.loads(info.read())['nuxeoPlatformMinVersion']
            log.debug("Fetched server minimum version for client version %s"
                      " from %s: %s", client_version, url, version)
            return version
        except HTTPError as e:
            log.error(e, exc_info=True)
            raise MissingUpdateSiteInfo(missing_msg)
        except URLError as e:
            log.error(e, exc_info=True)
            raise UnavailableUpdateSite("Cannot connect to update site '%s'"
                                        % self.update_site)
        except Exception as e:
            log.error(e, exc_info=True)
            raise MissingUpdateSiteInfo(missing_msg)

    def get_client_min_version(self, server_version):
        info_file = server_version + '.json'
        missing_msg = (
            "Missing or invalid file '%s' in update site '%s', can't get"
            " client minimum version for server version %s" % (
                                info_file, self.update_site, server_version))
        try:
            if not self.local_update_site:
                url = urljoin(self.update_site, info_file)
            else:
                url = info_file
            info = self.esky_app.version_finder.open_url(url)
            version = json.loads(info.read())['nuxeoDriveMinVersion']
            log.debug("Fetched client minimum version for server version %s"
                      " from %s: %s", server_version, url, version)
            return version
        except HTTPError as e:
            log.error(e, exc_info=True)
            raise MissingUpdateSiteInfo(missing_msg)
        except URLError as e:
            log.error(e, exc_info=True)
            raise UnavailableUpdateSite("Cannot connect to update site '%s'"
                                        % self.update_site)
        except Exception as e:
            log.error(e, exc_info=True)
            raise MissingUpdateSiteInfo(missing_msg)

    def get_latest_compatible_version(self, server_version):
        client_min_version = self.get_client_min_version(server_version)
        latest_version = None
        client_versions = self.find_versions()
        client_versions.append(self.get_current_latest_version())
        client_versions = sorted(client_versions, cmp=version_compare)
        for client_version in client_versions:
            if client_min_version <= client_version:
                server_min_version = self.get_server_min_version(
                                                    client_version)
                if server_min_version <= server_version:
                    latest_version = client_version
        if latest_version is None:
            raise MissingCompatibleVersion(
                    "No client version compatible with server version %s"
                    " available in update site '%s'" % (
                                server_version, self.update_site))
        return latest_version

    def get_update_status(self, client_version, server_version):
        try:
            latest_version = self.get_latest_compatible_version(server_version)
            if (client_version == latest_version):
                log.info("Client version %s is up-to-date regarding server"
                         " version %s.", client_version, server_version)
                return (UPDATE_STATUS_UP_TO_DATE, None)

            client_min_version = self.get_client_min_version(server_version)
            server_min_version = self.get_server_min_version(client_version)

            if version_compare(client_version, client_min_version) < 0:
                log.info("Client version %s is lighter than %s, the minimum"
                         " version compatible with the server version %s."
                         " An upgrade to version %s is needed.",
                         client_version, client_min_version, server_version,
                         latest_version)
                return (UPDATE_STATUS_UPGRADE_NEEDED, latest_version)

            if version_compare(server_version, server_min_version) < 0:
                log.info("Server version %s is lighter than %s, the minimum"
                         " version compatible with the client version %s."
                         " A downgrade to version %s is needed.",
                         server_version, server_min_version, client_version,
                         latest_version)
                return (UPDATE_STATUS_DOWNGRADE_NEEDED, latest_version)

            log.info("Client version %s is compatible with server version %s,"
                     " yet an update is available: version %s.",
                     client_version, server_version, latest_version)
            return (UPDATE_STATUS_UPDATE_AVAILABLE, latest_version)
        except UnavailableUpdateSite as e:
            log.warning(e)
            return (UPDATE_STATUS_UNAVAILABLE_SITE, None)
        except MissingUpdateSiteInfo as e:
            log.warning(e)
            return (UPDATE_STATUS_MISSING_INFO, None)
        except MissingCompatibleVersion as e:
            log.warning(e)
            return (UPDATE_STATUS_MISSING_VERSION, None)

    def update(self, version):
        if sys.platform == 'win32':
            # Try to update frozen application with the given version. If it
            # fails with a permission error, escalate to root and try again.
            try:
                self.esky_app.get_root()
                self._do_update(version)
                self.esky_app.drop_root()
                return True
            except EnvironmentError as e:
                if e.errno == errno.EINVAL:
                    # Under Windows, this means that the sudo popup was
                    # rejected
                    self.esky_app.sudo_proxy = None
                    raise RootPrivilegeRequired(e)
                # Other EnvironmentError, probably not related to permissions
                raise UpdateError(e)
            except Exception as e:
                # Error during update process, not related to permissions
                raise UpdateError(e)
        else:
            try:
                self._do_update(version)
                return True
            except Exception as e:
                raise UpdateError(e)

    def _update_callback(self, status):
        if "received" in status and "size" in status:
            self.action.progress = (status["received"] * 100 / status["size"])

    def _do_update_thread(self, version):
        log.info("Starting application update process")
        log.info("Fetching version %s from update site %s", version,
                      self.update_site)
        self.esky_app.fetch_version(version, self._update_callback)
        self.action.progress = None
        self.action.type = "Installing %s version" % version
        log.info("Installing version %s", version)
        self.esky_app.install_version(version)
        self.action.type = "Reinitializing"
        log.debug("Reinitializing Esky internal state")
        self.esky_app.reinitialize()
        log.info("Ended application update process")
        self.action.finish_action()

    def _do_update(self, version):
        from nxdrive.activity import Action
        from nxdrive.gui.progress_dialog import ProgressDialog
        from threading import Thread
        update_thread = Thread(target=self._do_update_thread,
                               args=[version])
        update_thread.start()
        self.action = Action("Downloading %s version" % version,
                                threadId=update_thread.ident)
        self.action.progress = 0
        progressDlg = ProgressDialog(self.action)
        progressDlg.exec_()

    def cleanup(self, version):
        log.info("Uninstalling version %s", version)
        self.esky_app.uninstall_version(version)
        log.info("Cleaning up Esky application", version)
        self.esky_app.cleanup()

    def get_update_label(self, status):
        return UPDATE_STATUS_LABEL[status]

    def get_update_site(self):
        return self.update_site
