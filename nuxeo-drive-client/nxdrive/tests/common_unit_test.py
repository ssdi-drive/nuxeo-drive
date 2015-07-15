"""Common test utilities"""
import os
import unittest
import tempfile
import hashlib
import shutil

from nxdrive.utils import safe_long_path
from nxdrive.client import RemoteDocumentClient
from nxdrive.client import RemoteFileSystemClient
from nxdrive.client import LocalClient
from nxdrive.manager import Manager
from nxdrive.logging_config import configure
from nxdrive.logging_config import get_logger
from nxdrive.tests.common import TEST_DEFAULT_DELAY
from nxdrive import __version__
from PyQt4 import QtCore
from threading import Thread
from time import sleep

WindowsError = None
try:
    from exceptions import WindowsError
except ImportError:
    pass  # This will never be raised under Unix

if 'DRIVE_YAPPI' in os.environ:
    import yappi

DEFAULT_WAIT_SYNC_TIMEOUT = 20
DEFAULT_WAIT_REMOTE_SCAN_TIMEOUT = 10


def configure_logger():
    configure(
        console_level='DEBUG',
        command_name='test',
        force_configure=True,
    )

# Configure test logger
configure_logger()
log = get_logger(__name__)


class TestThread(QtCore.QThread):
    def __init__(self, method, method_arg):
        super(TestThread, self).__init__()
        self._method = method
        self._method_arg = method_arg

    def run(self):
        self._method(self._method_arg)


class TestQApplication(QtCore.QCoreApplication):

    def __init__(self, argv, method, method_arg):
        super(TestQApplication, self).__init__(argv)
        self._test_thread = TestThread(method, method_arg)
        self._test_thread.start()


class UnitTestCase(unittest.TestCase):

    TEST_WORKSPACE_PATH = (
        u'/default-domain/workspaces/nuxeo-drive-test-workspace')
    FS_ITEM_ID_PREFIX = u'defaultFileSystemItemFactory#default#'

    EMPTY_DIGEST = hashlib.md5().hexdigest()
    SOME_TEXT_CONTENT = b"Some text content."
    SOME_TEXT_DIGEST = hashlib.md5(SOME_TEXT_CONTENT).hexdigest()

    # 1s time resolution as we truncate remote last modification time to the
    # seconds in RemoteFileSystemClient.file_to_info() because of the datetime
    # resolution of some databases (MySQL...)
    REMOTE_MODIFICATION_TIME_RESOLUTION = 1.0

    # 1s resolution on HFS+ on OSX
    # 2s resolution on FAT but can be ignored as no Jenkins is running the test
    # suite under windows on FAT partitions
    # ~0.01s resolution for NTFS
    # 0.001s for EXT4FS
    OS_STAT_MTIME_RESOLUTION = 1.0

    # Nuxeo max length for document name
    DOC_NAME_MAX_LENGTH = 24

    def setUpApp(self, server_profile=None):
        # Check the Nuxeo server test environment
        self.nuxeo_url = os.environ.get('NXDRIVE_TEST_NUXEO_URL')
        self.admin_user = os.environ.get('NXDRIVE_TEST_USER')
        self.password = os.environ.get('NXDRIVE_TEST_PASSWORD')
        self.workspace = os.environ.get('WORKSPACE')
        self.result = None
        self.tearedDown = False

        # Take default parameter if none has been set
        if self.nuxeo_url is None:
            self.nuxeo_url = "http://localhost:8080/nuxeo"
        if self.admin_user is None:
            self.admin_user = "Administrator"
        if self.password is None:
            self.password = "Administrator"
        self.tmpdir = None
        if self.workspace is not None:
            self.tmpdir = os.path.join(self.workspace, "tmp")
            if not os.path.isdir(self.tmpdir):
                os.makedirs(self.tmpdir)

        if None in (self.nuxeo_url, self.admin_user, self.password):
            raise unittest.SkipTest(
                "No integration server configuration found in environment.")

        # Check the local filesystem test environment
        self.local_test_folder_1 = tempfile.mkdtemp(u'-nxdrive-tests-user-1', dir=self.tmpdir)
        self.local_test_folder_2 = tempfile.mkdtemp(u'-nxdrive-tests-user-2', dir=self.tmpdir)

        self.local_nxdrive_folder_1 = os.path.join(
            self.local_test_folder_1, u'Nuxeo Drive')
        os.mkdir(self.local_nxdrive_folder_1)
        self.local_nxdrive_folder_2 = os.path.join(
            self.local_test_folder_2, u'Nuxeo Drive')
        os.mkdir(self.local_nxdrive_folder_2)

        self.nxdrive_conf_folder_1 = os.path.join(
            self.local_test_folder_1, u'nuxeo-drive-conf')
        os.mkdir(self.nxdrive_conf_folder_1)
        self.nxdrive_conf_folder_2 = os.path.join(
            self.local_test_folder_2, u'nuxeo-drive-conf')
        os.mkdir(self.nxdrive_conf_folder_2)

        from mock import Mock
        options = Mock()
        options.debug = False
        options.delay = TEST_DEFAULT_DELAY
        options.force_locale = None
        options.proxy_server = None
        options.log_level_file = None
        options.update_site_url = None
        options.beta_update_site_url = None
        options.nxdrive_home = self.nxdrive_conf_folder_1
        self.manager_1 = Manager(options)
        options.nxdrive_home = self.nxdrive_conf_folder_2
        Manager._singleton = None
        self.manager_2 = Manager(options)
        self.version = __version__
        # Long timeout for the root client that is responsible for the test
        # environment set: this client is doing the first query on the Nuxeo
        # server and might need to wait for a long time without failing for
        # Nuxeo to finish initialize the repo on the first request after
        # startup
        root_remote_client = RemoteDocumentClient(
            self.nuxeo_url, self.admin_user,
            u'nxdrive-test-administrator-device', self.version,
            password=self.password, base_folder=u'/', timeout=60)

        # Activate given profile if needed, eg. permission hierarchy
        if server_profile is not None:
            root_remote_client.activate_profile(server_profile)

        # Call the Nuxeo operation to setup the integration test environment
        credentials = root_remote_client.execute(
            "NuxeoDrive.SetupIntegrationTests",
            userNames="user_1, user_2", permission='ReadWrite')

        credentials = [c.strip().split(u":") for c in credentials.split(u",")]
        self.user_1, self.password_1 = credentials[0]
        self.user_2, self.password_2 = credentials[1]
        self.engine_1 = self.manager_1.bind_server(self.local_nxdrive_folder_1, self.nuxeo_url, self.user_1,
                                                   self.password_1, start_engine=False)
        self.engine_2 = self.manager_2.bind_server(self.local_nxdrive_folder_2, self.nuxeo_url, self.user_2,
                                                   self.password_2, start_engine=False)
        self.engine_1.syncCompleted.connect(self.sync_completed)
        self.engine_1.get_remote_watcher().remoteScanFinished.connect(self.remote_scan_completed)
        self.engine_1.get_remote_watcher().changesFound.connect(self.remote_changes_found)
        self.engine_2.syncCompleted.connect(self.sync_completed)
        self.engine_2.get_remote_watcher().remoteScanFinished.connect(self.remote_scan_completed)
        self.engine_2.get_remote_watcher().changesFound.connect(self.remote_changes_found)
        self.queue_manager_1 = self.engine_1.get_queue_manager()
        self.queue_manager_2 = self.engine_2.get_queue_manager()

        ws_info = root_remote_client.fetch(self.TEST_WORKSPACE_PATH)
        self.workspace = ws_info[u'uid']
        self.workspace_title = ws_info[u'title']

        self.sync_root_folder_1 = os.path.join(self.local_nxdrive_folder_1, self.workspace_title)
        self.sync_root_folder_2 = os.path.join(self.local_nxdrive_folder_2, self.workspace_title)

        self.local_root_client_1 = self.engine_1.get_local_client()
        self.local_root_client_2 = self.engine_2.get_local_client()
        self.local_client_1 = LocalClient(os.path.join(self.local_nxdrive_folder_1, self.workspace_title))
        self.local_client_2 = LocalClient(os.path.join(self.local_nxdrive_folder_2, self.workspace_title))

        # Document client to be used to create remote test documents
        # and folders
        self.upload_tmp_dir = tempfile.mkdtemp(u'-nxdrive-uploads', dir=self.tmpdir)
        remote_document_client_1 = RemoteDocumentClient(
            self.nuxeo_url, self.user_1, u'nxdrive-test-device-1',
            self.version,
            password=self.password_1, base_folder=self.workspace,
            upload_tmp_dir=self.upload_tmp_dir)

        remote_document_client_2 = RemoteDocumentClient(
            self.nuxeo_url, self.user_2, u'nxdrive-test-device-2',
            self.version,
            password=self.password_2, base_folder=self.workspace,
            upload_tmp_dir=self.upload_tmp_dir)

        # File system client to be used to create remote test documents
        # and folders
        remote_file_system_client_1 = RemoteFileSystemClient(
            self.nuxeo_url, self.user_1, u'nxdrive-test-device-1',
            self.version,
            password=self.password_1, upload_tmp_dir=self.upload_tmp_dir)

        remote_file_system_client_2 = RemoteFileSystemClient(
            self.nuxeo_url, self.user_2, u'nxdrive-test-device-2',
            self.version,
            password=self.password_2, upload_tmp_dir=self.upload_tmp_dir)

        # Register root
        remote_document_client_1.register_as_root(self.workspace)

        self.root_remote_client = root_remote_client
        self.remote_document_client_1 = remote_document_client_1
        self.remote_document_client_2 = remote_document_client_2
        self.remote_file_system_client_1 = remote_file_system_client_1
        self.remote_file_system_client_2 = remote_file_system_client_2

        self._wait_sync = {self.engine_1.get_uid(): True, self.engine_2.get_uid(): True}
        self._wait_remote_scan = {self.engine_1.get_uid(): True, self.engine_2.get_uid(): True}
        self._remote_changes_count = {self.engine_1.get_uid(): 0, self.engine_2.get_uid(): 0}

    @QtCore.pyqtSlot(str)
    def sync_completed(self, uid):
        uid = str(uid)
        if not uid:
            for uid in self._wait_sync.iterkeys():
                self._wait_sync[uid] = False
        else:
            self._wait_sync[uid] = False

    def wait_sync(self, wait_for_async=False, timeout=DEFAULT_WAIT_SYNC_TIMEOUT, fail_if_timeout=True,
                  wait_for_engine_1=True, wait_for_engine_2=False):
        log.debug("Wait for sync")
        # First wait for server if needed
        if wait_for_async:
            self.wait()
        self._wait_sync = {
            self.engine_1.get_uid(): wait_for_engine_1,
            self.engine_2.get_uid(): wait_for_engine_2
        }
        while timeout > 0:
            sleep(1)
            if sum(self._wait_sync.values()) == 0:
                if wait_for_async:
                    log.debug('Sync completed, _wait_remote_scan = %r, remote changes = %r',
                              self._wait_remote_scan, self._remote_changes_count)
                    wait_remote_scan = False
                    if wait_for_engine_1:
                        wait_remote_scan = self._wait_remote_scan[self.engine_1.get_uid()]
                    if wait_for_engine_2:
                        wait_remote_scan = wait_remote_scan or self._wait_remote_scan[self.engine_2.get_uid()]
                    is_remote_changes = True
                    if wait_for_engine_1:
                        is_remote_changes = self._remote_changes_count[self.engine_1.get_uid()] > 0
                    if wait_for_engine_2:
                        is_remote_changes = (is_remote_changes
                                             and self._remote_changes_count[self.engine_2.get_uid()] > 0)
                    if (not wait_remote_scan or is_remote_changes):
                        self._wait_remote_scan = {self.engine_1.get_uid(): wait_for_engine_1,
                                                  self.engine_2.get_uid(): wait_for_engine_2}
                        self._remote_changes_count = {self.engine_1.get_uid(): 0, self.engine_2.get_uid(): 0}
                        log.debug('Ended wait for sync, setting _wait_remote_scan values to True'
                                  ' and _remote_changes_count values to 0')
                        return
                else:
                    log.debug("Sync completed, ended wait for sync")
                    return
            timeout = timeout - 1
        if fail_if_timeout:
            self.fail("Wait for sync timeout expired")
        else:
            log.debug("Wait for sync timeout")

    @QtCore.pyqtSlot(str)
    def remote_scan_completed(self, uid):
        uid = str(uid)
        log.debug('Remote scan completed for engine %s', uid)
        self._wait_remote_scan[uid] = False

    @QtCore.pyqtSlot(str, int)
    def remote_changes_found(self, uid, change_count):
        uid = str(uid)
        change_count = int(change_count)
        self._remote_changes_count[uid] = change_count

    def wait_remote_scan(self, timeout=DEFAULT_WAIT_REMOTE_SCAN_TIMEOUT, wait_for_engine_1=True,
                         wait_for_engine_2=False):
        log.debug("Wait for remote scan")
        self._wait_remote_scan = {self.engine_1.get_uid(): wait_for_engine_1,
                                  self.engine_2.get_uid(): wait_for_engine_2}
        while timeout > 0:
            sleep(1)
            if sum(self._wait_remote_scan.values()) == 0:
                log.debug("Ended wait for remote scan")
                return
            timeout = timeout - 1
        self.fail("Wait for remote scan timeout expired")

    def is_profiling(self):
        return 'DRIVE_YAPPI' in os.environ and yappi is not None

    def setup_profiler(self):
        if not self.is_profiling():
            return
        yappi.start()

    def teardown_profiler(self):
        if not self.is_profiling():
            return
        path = os.environ["DRIVE_YAPPI"]
        if not os.path.exists(path):
            os.mkdir(path)
        report_path = os.path.join(path, self.id() + '-yappi-threads')
        with open(report_path,'w') as fd:
            columns={0:("name",80), 1:("tid", 15), 2:("ttot", 8), 3:("scnt", 10)}
            yappi.get_thread_stats().print_all(out=fd, columns=columns)
        report_path = os.path.join(path, self.id() + '-yappi-fcts')
        with open(report_path,'w') as fd:
            columns={0:("name",80), 1:("ncall", 5), 2:("tsub", 8), 3:("ttot", 8), 4:("tavg",8)}
            stats = yappi.get_func_stats()
            stats.strip_dirs()
            stats.print_all(out=fd, columns=columns)
        log.debug("Profiler Report generated in '%s'", report_path)

    def run(self, result=None):
        self.app = QtCore.QCoreApplication([])
        self.setUpApp()
        self.result = result

        # TODO Should use a specific application
        def launch_test():
            log.debug("UnitTest thread started")
            sleep(1)
            self.setup_profiler()
            super(UnitTestCase, self).run(result)
            self.teardown_profiler()
            self.app.quit()
            log.debug("UnitTest thread finished")

        sync_thread = Thread(target=launch_test)
        sync_thread.start()
        self.app.exec_()
        sync_thread.join(30)
        self.tearDownApp()
        del self.app
        log.debug("UnitTest run finished")

    def tearDown(self):
        unittest.TestCase.tearDown(self)
        if not self.tearedDown:
            self.tearDownApp()

    def tearDownApp(self, server_profile=None):
        if self.tearedDown:
            return
        import sys
        if sys.exc_info() != (None, None, None):
            self.generate_report()
        elif self.result is not None:
            if hasattr(self.result, "wasSuccessful") and not self.result.wasSuccessful():
                self.generate_report()
        log.debug("TearDown unit test")
        # Unbind all
        self.manager_1.unbind_all()
        self.manager_1._dao.dispose()
        self.manager_2.unbind_all()
        self.manager_2._dao.dispose()
        Manager._singleton = None
        # Don't need to revoke tokens for the file system remote clients
        # since they use the same users as the remote document clients
        self.root_remote_client.execute("NuxeoDrive.TearDownIntegrationTests")

        # Deactivate given profile if needed, eg. permission hierarchy
        if server_profile is not None:
            self.root_remote_client.deactivate_profile(server_profile)

        self._clean_dir(self.upload_tmp_dir)
        self._clean_dir(self.local_test_folder_1)
        self._clean_dir(self.local_test_folder_2)

        del self.engine_1
        self.engine_1 = None
        del self.engine_2
        self.engine_2 = None
        del self.local_client_1
        self.local_client_1 = None
        del self.local_client_2
        self.local_client_2 = None
        del self.remote_document_client_1
        self.remote_document_client_1 = None
        del self.remote_document_client_2
        self.remote_document_client_2 = None
        del self.remote_file_system_client_1
        self.remote_file_system_client_1 = None
        del self.remote_file_system_client_2
        self.remote_file_system_client_2 = None
        self.tearedDown = True

    def _clean_dir(self, _dir):
        if os.path.exists(_dir):
            to_remove = safe_long_path(_dir)
            try:
                shutil.rmtree(to_remove)
            except Exception as e:
                if type(e) == WindowsError:
                    os.system('rmdir /S /Q %s' % to_remove)

    def _interact(self, pause=0):
        self.app.processEvents()
        if pause > 0:
            sleep(pause)
        while (self.app.hasPendingEvents()):
            self.app.processEvents()

    def make_local_tree(self, root=None, local_client=None):
        if local_client is None:
            local_client = self.local_root_client_1
        if root is None:
            root = u"/" + self.workspace_title
            if not local_client.exists(root):
                local_client.make_folder(u"/", self.workspace_title)
        # create some folders
        folder_1 = local_client.make_folder(root, u'Folder 1')
        folder_1_1 = local_client.make_folder(folder_1, u'Folder 1.1')
        folder_1_2 = local_client.make_folder(folder_1, u'Folder 1.2')
        folder_2 = local_client.make_folder(root, u'Folder 2')

        # create some files
        local_client.make_file(folder_2, u'Duplicated File.txt', content=b"Some content.")

        local_client.make_file(folder_1, u'File 1.txt', content=b"aaa")
        local_client.make_file(folder_1_1, u'File 2.txt', content=b"bbb")
        local_client.make_file(folder_1_2, u'File 3.txt', content=b"ccc")
        local_client.make_file(folder_2, u'File 4.txt', content=b"ddd")
        local_client.make_file(root, u'File 5.txt', content=b"eee")
        return (6, 5)

    def make_server_tree(self):
        remote_client = self.remote_document_client_1
        # create some folders on the server
        folder_1 = remote_client.make_folder(self.workspace, u'Folder 1')
        folder_1_1 = remote_client.make_folder(folder_1, u'Folder 1.1')
        folder_1_2 = remote_client.make_folder(folder_1, u'Folder 1.2')
        folder_2 = remote_client.make_folder(self.workspace, u'Folder 2')

        # create some files on the server
        remote_client.make_file(folder_2, u'Duplicated File.txt',
                                content=b"Some content.")
        remote_client.make_file(folder_2, u'Duplicated File.txt',
                                content=b"Other content.")

        remote_client.make_file(folder_1, u'File 1.txt', content=b"aaa")
        remote_client.make_file(folder_1_1, u'File 2.txt', content=b"bbb")
        remote_client.make_file(folder_1_2, u'File 3.txt', content=b"ccc")
        remote_client.make_file(folder_2, u'File 4.txt', content=b"ddd")
        remote_client.make_file(self.workspace, u'File 5.txt', content=b"eee")
        return (7, 4)

    def get_full_queue(self, queue, dao=None):
        if dao is None:
            dao = self.engine_1.get_dao()
        result = []
        while (len(queue) > 0):
            result.append(dao.get_state_from_id(queue.pop().id))
        return result

    def generate_report(self):
        if "REPORT_PATH" not in os.environ:
            return
        report_path = os.path.join(os.environ["REPORT_PATH"], self.id())
        self.manager_1.generate_report(report_path)
        log.debug("Report generated in '%s'", report_path)

    def wait(self, retry=3):
        try:
            self.root_remote_client.wait()
        except OSError.TimeoutError as e:
            log.debug("Exception while waiting for server : %r", e)
            # Not the nicest
            if retry > 0:
                log.debug("Retry to wait")
                self.wait(retry - 1)
