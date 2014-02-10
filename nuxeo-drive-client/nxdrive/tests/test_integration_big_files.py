import os
import time
from shutil import copyfile

from nxdrive.tests.common import IntegrationTestCase
from nxdrive.client import LocalClient


class TestIntegrationBigFiles(IntegrationTestCase):

    def test_synchronize_big_file_downstream(self):

        # Bind the server and root workspace
        ctl = self.controller_1
        ctl.bind_server(self.local_nxdrive_folder_1, self.nuxeo_url,
                        self.user_1, self.password_1)
        ctl.bind_root(self.local_nxdrive_folder_1, self.workspace)

        # Launch first synchronization
        time.sleep(self.AUDIT_CHANGE_FINDER_TIME_RESOLUTION)
        self.wait()
        syn = ctl.synchronizer
        syn.loop(delay=0.1, max_loops=1)

        # Get local and remote clients
        local = LocalClient(os.path.join(self.local_nxdrive_folder_1,
                                         self.workspace_title))
        remote = self.remote_document_client_1

        # Create a big file in the remote root workspace then synchronize
        big_file_name = 'huge_file.zip'
        big_file_path = os.path.join(self.upload_tmp_dir, big_file_name)
        copyfile('resources/' + big_file_name, big_file_path)
        remote.stream_file(self.workspace, big_file_name, big_file_path)
        self.assertTrue(remote.exists('/' + big_file_name))

        time.sleep(self.AUDIT_CHANGE_FINDER_TIME_RESOLUTION)
        self.wait()
        syn.loop(delay=0.1, max_loops=1)
        self.assertTrue(local.exists('/' + big_file_name))

    def test_synchronize_big_file_upstream(self):

        # Bind the server and root workspace
        ctl = self.controller_1
        ctl.bind_server(self.local_nxdrive_folder_1, self.nuxeo_url,
                        self.user_1, self.password_1)
        ctl.bind_root(self.local_nxdrive_folder_1, self.workspace)

        # Launch first synchronization
        time.sleep(self.AUDIT_CHANGE_FINDER_TIME_RESOLUTION)
        self.wait()
        syn = ctl.synchronizer
        syn.loop(delay=0.1, max_loops=1)

        # Get local and remote clients
        local = LocalClient(os.path.join(self.local_nxdrive_folder_1,
                                         self.workspace_title))
        remote = self.remote_document_client_1

        # Create a big file in the remote root workspace then synchronize
        big_file_name = 'huge_file.zip'
        big_file_path = os.path.join(self.local_nxdrive_folder_1,
                                     self.workspace_title,
                                     big_file_name)
        copyfile('resources/' + big_file_name, big_file_path)
        self.assertTrue(local.exists('/' + big_file_name))

        syn.loop(delay=0.1, max_loops=1)
        self.assertTrue(remote.exists('/' + big_file_name))
