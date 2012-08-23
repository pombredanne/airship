import os
import pwd
import json
import tempfile
try:
    import unittest2 as unittest
except ImportError:
    import unittest
from path import path
from mock import patch
from importlib import import_module as imp


def configure_deployment(sarge_home, config):
    deployment_config_folder = (sarge_home /
                                imp('sarge.core').DEPLOYMENT_CFG_DIR)
    imp('sarge.util').ensure_folder(deployment_config_folder)
    filename = config['name'] + '.yaml'
    with open(deployment_config_folder / filename, 'wb') as f:
        json.dump(config, f)


class SargeTestCase(unittest.TestCase):

    def sarge(self, config=None):
        if config is None:
            config = {}
        cfg_path = self.tmp / imp('sarge.core').SARGE_CFG
        if cfg_path.isfile():
            with open(cfg_path, 'rb') as f:
                config.update(json.load(f))
        config['home'] = self.tmp
        return imp('sarge').Sarge(config)

    def patch(self, name):
        p = patch(name)
        mock_ob = p.start()
        self.addCleanup(p.stop)
        return mock_ob

    def _pre_setup(self):
        self.tmp = path(tempfile.mkdtemp())
        self.addCleanup(self.tmp.rmtree)
        self.mock_subprocess = self.patch('sarge.daemons.subprocess')

    def __call__(self, result=None):
        self._pre_setup()
        super(SargeTestCase, self).__call__(result)
