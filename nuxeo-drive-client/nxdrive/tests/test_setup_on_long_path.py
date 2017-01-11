'''
Created on Jan 9, 2017

@author: mkeshava
'''
from common_unit_test import UnitTestCase
import os


test_folder = 'A' * 200


class TestSetupOnLongPath(UnitTestCase):
    def test_setup_on_long_path(self):
        self.engine_1.stop()

        self.local_nxdrive_folder_1 = os.path.join(self.local_nxdrive_folder_1, test_folder)

        self.engine_1 = self.manager_1.bind_server(self.local_nxdrive_folder_1, self.nuxeo_url, self.user_2,
                                                   self.password_2, start_engine=False)

        self.engine_1.start()
        self.engine_1.stop()
