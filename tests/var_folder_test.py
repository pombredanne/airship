import tempfile
import json
from path import path
from mock import patch
from utils import unittest
from utils import configure_deployment, configure_sarge, username


def setUpModule(self):
    import sarge; self.sarge = sarge
    self._subprocess_patch = patch('sarge.subprocess')
    self.mock_subprocess = self._subprocess_patch.start()


class VarFolderTest(unittest.TestCase):

    def setUp(self):
        self.tmp = path(tempfile.mkdtemp())
        self.addCleanup(self.tmp.rmtree)
        configure_sarge(self.tmp, {'plugins': ['sarge:VarFolderPlugin']})

    def configure_and_deploy(self):
        configure_deployment(self.tmp, {
            'name': 'testy',
            'user': username,
            'require-services': [
                {'type': 'var-folder', 'name': 'db'},
            ],
        })
        s = sarge.Sarge(self.tmp)
        testy = s.get_deployment('testy')
        version_folder = testy.new_version()
        testy.activate_version(version_folder)
        return version_folder

    def test_deploy_passes_var_folder_to_deployment(self):
        version_folder = self.configure_and_deploy()
        cfg_folder = path(version_folder + '.cfg')
        with (cfg_folder / sarge.APP_CFG).open() as f:
            appcfg = json.load(f)
        db_path = self.tmp / 'var' / 'testy' / 'db'
        self.assertEqual(appcfg['services']['db'], db_path)
