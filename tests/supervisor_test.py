import unittest
import tempfile
import json
import sys
import ConfigParser
from path import path
from mock import patch, call
from utils import configure_sarge, configure_deployment


def setUpModule(self):
    import sarge; self.sarge = sarge
    self._subprocess_patch = patch('sarge.subprocess')
    self.mock_subprocess = self._subprocess_patch.start()


def tearDownModule(self):
    self._subprocess_patch.stop()


def read_config(cfg_path):
    import ConfigParser
    config = ConfigParser.RawConfigParser()
    config.read([cfg_path])
    return config


MISSING = object()


def config_file_checker(cfg_path):
    config = read_config(cfg_path)

    def eq_config(section, field, ok_value):
        try:
            cfg_value = config.get(section, field)
        except ConfigParser.NoOptionError:
            cfg_value = MISSING
        msg = 'Configuration field [%s] %s\n%r != %r' % (
            section, field, cfg_value, ok_value)
        assert cfg_value == ok_value, msg

    return eq_config


class SupervisorConfigurationTest(unittest.TestCase):

    def setUp(self):
        self.tmp = path(tempfile.mkdtemp())
        self.addCleanup(self.tmp.rmtree)

    def test_enumerate_deployments(self):
        configure_deployment(self.tmp, {'name': 'testy'})
        s = sarge.Sarge(self.tmp)
        self.assertEqual([d.name for d in s.deployments], ['testy'])

    def test_generate_supervisord_cfg_with_no_deployments(self):
        s = sarge.Sarge(self.tmp)
        s.generate_supervisord_configuration()

        eq_config = config_file_checker(self.tmp/sarge.SUPERVISORD_CFG)

        eq_config('unix_http_server', 'file', self.tmp/'supervisord.sock')
        eq_config('rpcinterface:supervisor', 'supervisor.rpcinterface_factory',
                  'supervisor.rpcinterface:make_main_rpcinterface')
        eq_config('supervisord', 'logfile', self.tmp/'supervisord.log')
        eq_config('supervisord', 'pidfile', self.tmp/'supervisord.pid')
        eq_config('supervisord', 'directory', self.tmp)
        eq_config('supervisorctl', 'serverurl',
                  'unix://' + self.tmp/'supervisord.sock')
        eq_config('include', 'files', 'run/*/supervisor_deploy.conf')

    def test_generate_supervisord_cfg_with_socket_owner(self):
        configure_sarge(self.tmp, {'supervisord_socket_owner': 'theone'})
        s = sarge.Sarge(self.tmp)
        s.generate_supervisord_configuration()

        eq_config = config_file_checker(self.tmp/sarge.SUPERVISORD_CFG)

        eq_config('unix_http_server', 'chown', 'theone')

    def test_generated_cfg_ignores_deployments_with_no_versions(self):
        configure_deployment(self.tmp, {'name': 'testy'})
        s = sarge.Sarge(self.tmp)
        s.generate_supervisord_configuration()

        config = read_config(self.tmp/sarge.SUPERVISORD_CFG)
        self.assertEqual(config.sections(),
                         ['unix_http_server', 'rpcinterface:supervisor',
                          'supervisord', 'supervisorctl', 'include'])

    def test_generate_supervisord_cfg_with_deployment_command(self):
        configure_deployment(self.tmp, {'name': 'testy',
                                        'command': "echo starting up"})
        s = sarge.Sarge(self.tmp)
        testy = s.get_deployment('testy')
        version_folder = testy.new_version()
        testy.activate_version(version_folder)

        run_folder = path(version_folder + '.run')
        eq_config = config_file_checker(run_folder/sarge.SUPERVISOR_DEPLOY_CFG)

        eq_config('program:testy', 'command', "echo starting up")
        eq_config('program:testy', 'redirect_stderr', 'true')
        eq_config('program:testy', 'stdout_logfile', run_folder/'stdout.log')
        eq_config('program:testy', 'startsecs', '2')
        eq_config('program:testy', 'autostart', 'false')
        eq_config('program:testy', 'autorestart', MISSING)

    def test_autorestart_option(self):
        configure_deployment(self.tmp, {'name': 'testy',
                                        'autorestart': 'always'})
        s = sarge.Sarge(self.tmp)
        testy = s.get_deployment('testy')
        version_folder = testy.new_version()
        testy.activate_version(version_folder)

        run_folder = path(version_folder + '.run')
        eq_config = config_file_checker(run_folder/sarge.SUPERVISOR_DEPLOY_CFG)

        eq_config('program:testy', 'autorestart', 'true')

    def test_user_option(self):
        configure_deployment(self.tmp, {'name': 'testy',
                                        'user': 'someone'})
        s = sarge.Sarge(self.tmp)
        testy = s.get_deployment('testy')
        version_folder = testy.new_version()
        testy.activate_version(version_folder)

        run_folder = path(version_folder + '.run')
        eq_config = config_file_checker(run_folder/sarge.SUPERVISOR_DEPLOY_CFG)

        eq_config('program:testy', 'user', 'someone')

    def test_get_deployment(self):
        configure_deployment(self.tmp, {'name': 'testy'})
        s = sarge.Sarge(self.tmp)
        testy = s.get_deployment('testy')
        self.assertEqual(testy.name, 'testy')

    def test_get_deployment_invalid_name(self):
        s = sarge.Sarge(self.tmp)
        with self.assertRaises(KeyError):
            testy = s.get_deployment('testy')

    def test_directory_updated_after_activation(self):
        configure_deployment(self.tmp, {'name': 'testy'})
        s = sarge.Sarge(self.tmp)
        testy = s.get_deployment('testy')
        version_folder = path(testy.new_version())
        testy.activate_version(version_folder)

        run_folder = path(version_folder + '.run')
        eq_config = config_file_checker(run_folder/sarge.SUPERVISOR_DEPLOY_CFG)
        eq_config('program:testy', 'directory', version_folder)


class SupervisorInvocationTest(unittest.TestCase):

    def setUp(self):
        self.tmp = path(tempfile.mkdtemp())
        self.addCleanup(self.tmp.rmtree)

    def test_invoke_supervisorctl(self):
        mock_subprocess.reset_mock()
        s = sarge.Sarge(self.tmp)
        s.supervisorctl(['hello', 'world!'])
        supervisorctl_path = path(sys.prefix).abspath()/'bin'/'supervisorctl'
        self.assertEqual(mock_subprocess.check_call.mock_calls,
                         [call([supervisorctl_path,
                                '-c', self.tmp/sarge.SUPERVISORD_CFG,
                                'hello', 'world!'])])
