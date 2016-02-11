import os
import shutil
import time

from nxdrive.tests.common_unit_test import UnitTestCase


class TestLocalRootDeletion(UnitTestCase):

    def setUp(self):

        self.root_deleted = False

        # Populate synchronization root and synchronize
        local = self.local_client_1
        self.make_server_tree(deep=False)
        self.engine_1.start()
        self.wait_sync(wait_for_async=True)
        self.assertTrue(local.exists('/'))
        self.assertEqual(len(local.get_children_info('/')), 3)

        # Remove root folder
        self.local_client_1.unlock_path(self.sync_root_folder_1)
        # Force the write mode under Windows
        import stat
        if os.access(self.local_nxdrive_folder_1, os.W_OK):
            os.chmod(self.local_nxdrive_folder_1,
                     stat.S_IXUSR | stat.S_IRGRP | stat.S_IXGRP |
                     stat.S_IRUSR | stat.S_IWGRP | stat.S_IWUSR)
        shutil.rmtree(self.local_nxdrive_folder_1, False)
        self.assertFalse(os.path.exists(self.local_nxdrive_folder_1))

        # Wait for deleted root FS event handler
        self.wait_root_deleted()

    def test_disconnect(self):
        # Simulate disconnection
        self.manager_1.unbind_engine(self.engine_1.get_uid())
        self.assertFalse(os.path.exists(self.local_nxdrive_folder_1))
        self.assertEquals(len(self.manager_1.get_engines()), 0)

    def test_recreate(self):
        # Simulate recreation
        self.engine_1.reinit()
        self.assertTrue(os.path.exists(self.local_nxdrive_folder_1))
        self.assertEquals(len(self.manager_1.get_engines()), 1)
        # Sleep to avoid Qt event handler exception (?)
        time.sleep(3)
