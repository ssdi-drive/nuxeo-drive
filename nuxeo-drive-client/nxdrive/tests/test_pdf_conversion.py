import os

from nxdrive.tests.common import IntegrationTestCase
from nxdrive.client import LocalClient


class TestPDFConversion(IntegrationTestCase):

    def test_pdf_conversion(self):
        # Bind the server and root workspace
        ctl = self.controller_1
        ctl.bind_server(self.local_nxdrive_folder_1, self.nuxeo_url,
                        self.user_1, self.password_1)
        ctl.bind_root(self.local_nxdrive_folder_1, self.workspace)

        # Get remote client
        remote_client = self.remote_document_client_1

        # Upload a document on the server
        file_path = self.get_resource_path('stepbystep-python.doc')
        remote_client.stream_file(self.workspace,
                                  'Step by step python installation.doc',
                                  file_path)
        # Check upload
        self.assertTrue(remote_client.exists(
                                  '/Step by step python installation.doc'))

        # Process synchronization
        self.synchronize(ctl)

        # Get local client
        local_client = LocalClient(os.path.join(self.local_nxdrive_folder_1,
                                         self.workspace_title))
        # Check remote document has been synchronized locally
        self.assertTrue(local_client.exists('/stepbystep-python.doc'))

        # Check file has been converted to PDF
        pdf_dir = os.path.join(os.path.expanduser(u'~'), u'mypdffiles')
        self.assertTrue(os.path.exists(pdf_dir))
        self.assertTrue(os.path.exists(os.path.join(pdf_dir,
                                                    'stepbystep-python.pdf')))
