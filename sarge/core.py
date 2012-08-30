import os
import sys
import logging
import json
import random
import string
import tempfile
from importlib import import_module
from path import path
import blinker
import yaml
from .daemons import Supervisor
from . import signals


log = logging.getLogger(__name__)


DEPLOYMENT_CFG_DIR = 'deployments'
CFG_LINKS_FOLDER = 'active'

QUICK_WSGI_APP_TEMPLATE = """\
#!%(python_bin)s
from flup.server.fcgi import WSGIServer
from importlib import import_module
appcfg = %(appcfg)r
app_factory = getattr(import_module(%(module_name)r), %(attribute_name)r)
app = app_factory(appcfg)
server = WSGIServer(app, bindAddress=%(socket_path)r, umask=0)
server.run()
"""


def _get_named_object(name):
    module_name, attr_name = name.split(':')
    module = import_module(module_name)
    return getattr(module, attr_name)


class Instance(object):

    def __init__(self, id_, sarge, config):
        self.id_ = id_
        self.sarge = sarge
        self.config = config
        self.folder = self.sarge._instance_folder(id_)
        var = self.sarge.home_path / 'var'
        self.run_folder = var / 'run' / id_
        self.appcfg_path = self.run_folder / 'appcfg.json'
        self.log_path = var / 'log' / (self.id_ + '.log')

    def start(self):
        log.info("Activating instance %r", self.id_)
        self.run_folder.makedirs_p()
        self._appcfg = {}
        signals.instance_configuring.send(self.sarge, instance=self,
                                                      appcfg=self._appcfg)
        signals.instance_will_start.send(self.sarge, instance=self,
                                                     appcfg=self._appcfg)
        if 'tmp-wsgi-app' in self.config:
            app_import_name = self.config['tmp-wsgi-app']
            script_path = self.folder / 'server'
            log.debug("Writing WSGI script for instance %r at %r.",
                      self.id_, script_path)
            with open(script_path, 'wb') as f:
                module_name, attribute_name = app_import_name.split(':')
                f.write(QUICK_WSGI_APP_TEMPLATE % {
                    'python_bin': sys.executable,
                    'module_name': module_name,
                    'attribute_name': attribute_name,
                    'socket_path': str(self.run_folder / 'wsgi-app.sock'),
                    'appcfg': self._appcfg,
                })
            script_path.chmod(0755)

        with self.appcfg_path.open('wb') as f:
            json.dump(self._appcfg, f, indent=2)

        self.sarge.daemons.start_instance(self)

    def stop(self):
        self.sarge.daemons.stop_instance(self)
        signals.instance_has_stopped.send(self.sarge, instance=self)

    def destroy(self):
        self.sarge.daemons.remove_instance(self.id_)
        signals.instance_will_be_destroyed.send(self.sarge, instance=self)
        if self.run_folder.isdir():
            self.run_folder.rmtree()
        if self.folder.isdir():
            self.folder.rmtree()
        self.sarge._instance_config_path(self.id_).unlink_p()


class Sarge(object):
    """ The sarge object implements most operations performed by sarge. It acts
    as container for deployments.
    """

    def __init__(self, config):
        self.home_path = config['home']
        self.config = config
        self.daemons = Supervisor(self.home_path / 'etc')
        self._plugins = []
        for plugin_name in self.config.get('plugins', []):
            plugin_factory = _get_named_object(plugin_name)
            self._plugins.append(plugin_factory(self))

    @property
    def cfg_links_folder(self):
        folder = self.home_path / CFG_LINKS_FOLDER
        if not folder.isdir():
            folder.makedirs()
        return folder

    def _instance_config_path(self, instance_id):
        return self.home_path / DEPLOYMENT_CFG_DIR / (instance_id + '.yaml')

    def generate_supervisord_configuration(self):
        self.daemons.configure(self.home_path)

    def get_instance(self, instance_id):
        config_path = self._instance_config_path(instance_id)
        if not config_path.isfile():
            raise KeyError

        return Instance(instance_id, self, yaml.load(config_path.bytes()))

    def _instance_folder(self, id_):
        return self.home_path / id_

    def _generate_instance_id(self):
        def random_id(size=6, vocabulary=string.letters + string.digits):
            return ''.join(random.choice(vocabulary) for c in range(size))
        for c in range(10):
            id_ = random_id()
            try:
                self._instance_folder(id_).mkdir()
            except OSError:
                continue
            else:
                return id_
        else:
            raise RuntimeError("Failed to generate unique instance ID")

    def new_instance(self, config={}):
        instance_id = self._generate_instance_id()
        (self.home_path / DEPLOYMENT_CFG_DIR).mkdir_p()
        with open(self._instance_config_path(instance_id), 'wb') as f:
            json.dump({
                'name': instance_id,
                'require-services': config.get('services', {}),
                'urlmap': config.get('urlmap', []),
            }, f)
        instance = self.get_instance(instance_id)
        return instance


class VarFolderPlugin(object):

    def __init__(self, sarge):
        self.sarge = sarge
        signals.instance_configuring.connect(self.configure, sarge)

    def configure(self, sarge, instance, appcfg, **extra):
        var = instance.sarge.home_path / 'var'
        var_tmp = var / 'tmp'
        services = instance.config.get('require-services', {})

        for name, record in services.iteritems():
            if record['type'] == 'var-folder':
                var_tmp.makedirs_p()
                service_path = tempfile.mkdtemp(dir=var_tmp)
                if not service_path.isdir():
                    service_path.makedirs()
                appcfg[name.upper() + '_PATH'] = service_path

            elif record['type'] == 'persistent-folder':
                service_path = var / 'data' / name
                if not service_path.isdir():
                    service_path.makedirs()
                appcfg[name.upper() + '_PATH'] = service_path


class ListenPlugin(object):

    RANDOM_PORT_RANGE = (40000, 59999)

    def __init__(self, sarge):
        self.sarge = sarge
        signals.instance_configuring.connect(self.configure, sarge)

    def configure(self, sarge, instance, appcfg, **extra):
        services = instance.config.get('require-services', {})
        for name, record in services.iteritems():
            if record['type'] == 'listen':
                if 'host' in record:
                    appcfg[name.upper() + '_HOST'] = record['host']
                if 'port' in record:
                    port = record['port']
                    if port == 'random':
                        port = random.randint(*self.RANDOM_PORT_RANGE)
                    appcfg[name.upper() + '_PORT'] = port


def init_cmd(sarge, args):
    log.info("Initializing sarge folder at %r.", sarge.home_path)
    (sarge.home_path / 'etc').mkdir_p()
    (sarge.home_path / 'var').mkdir_p()
    (sarge.home_path / 'var' / 'log').mkdir_p()
    (sarge.home_path / 'var' / 'run').mkdir_p()
    (sarge.home_path / DEPLOYMENT_CFG_DIR).mkdir_p()
    signals.sarge_initializing.send(sarge)
    sarge.generate_supervisord_configuration()


def new_cmd(sarge, args):
    print sarge.new_instance(json.loads(args.config)).folder


def start_cmd(sarge, args):
    sarge.get_instance(args.id).start()


def stop_cmd(sarge, args):
    sarge.get_instance(args.id).stop()


def destroy_cmd(sarge, args):
    sarge.get_instance(args.id).destroy()


def shell_cmd(sarge, args):
    instance = sarge.get_instance(args.id)
    os.chdir(instance.folder)
    environ = dict(os.environ,
                   SARGEAPP_CFG=instance.appcfg_path)
    os.execve('/bin/bash', ['/bin/bash', '--norc'], environ)


def build_args_parser():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('sarge_home')
    subparsers = parser.add_subparsers()
    init_parser = subparsers.add_parser('init')
    init_parser.set_defaults(func=init_cmd)
    new_parser = subparsers.add_parser('new')
    new_parser.set_defaults(func=new_cmd)
    new_parser.add_argument('config')
    start_parser = subparsers.add_parser('start')
    start_parser.set_defaults(func=start_cmd)
    start_parser.add_argument('id')
    stop_parser = subparsers.add_parser('stop')
    stop_parser.set_defaults(func=stop_cmd)
    stop_parser.add_argument('id')
    destroy_parser = subparsers.add_parser('destroy')
    destroy_parser.set_defaults(func=destroy_cmd)
    destroy_parser.add_argument('id')
    shell_parser = subparsers.add_parser('shell')
    shell_parser.set_defaults(func=shell_cmd)
    shell_parser.add_argument('id')
    return parser


def set_up_logging(sarge_home):
    log_folder = sarge_home / 'var' / 'log'
    log_folder.makedirs_p()
    handler = logging.FileHandler(log_folder / 'sarge.log')
    log_format = "%(asctime)s %(levelname)s:%(name)s %(message)s"
    handler.setFormatter(logging.Formatter(log_format))
    handler.setLevel(logging.DEBUG)
    logging.getLogger().addHandler(handler)


def main(raw_arguments=None):
    parser = build_args_parser()
    args = parser.parse_args(raw_arguments or sys.argv[1:])
    sarge_home = path(args.sarge_home).abspath()
    set_up_logging(sarge_home)
    with open(sarge_home / 'etc' / 'sarge.yaml', 'rb') as f:
        config = yaml.load(f)
    config['home'] = sarge_home
    sarge = Sarge(config)
    args.func(sarge, args)


if __name__ == '__main__':
    main()
