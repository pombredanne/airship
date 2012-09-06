import logging
from string import Template
from . import signals


log = logging.getLogger(__name__)


def interpolate_config(raw_entry, appcfg):
    def interpolate(value):
        return Template(value).substitute(appcfg)
    return dict((k, interpolate(v)) for k, v in raw_entry.iteritems())


class NginxConfGenerator(object):
    """ Generate Nginx configuration snippets. """

    STATIC_TEMPLATE = (
        'location %(url)s {\n'
        '    alias %(folder)s/%(path)s;\n'
        '}\n')

    FCGI_TEMPLATE = (
        'location %(url)s {\n'
        '    include %(fcgi_params_path)s;\n'
        '    fastcgi_param PATH_INFO $fastcgi_script_name;\n'
        '    fastcgi_param SCRIPT_NAME "";\n'
        '    fastcgi_pass %(socket)s;\n'
        '}\n')

    PROXY_TEMPLATE = (
        'location %(url)s {\n'
        '    proxy_pass %(upstream_url)s;\n'
        '    proxy_redirect off;\n'
        '    proxy_set_header Host $host;\n'
        '    proxy_set_header X-Real-IP $remote_addr;\n'
        '    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\n'
        '}\n')

    fcgi_params_path = '/etc/nginx/fastcgi_params'

    def route(self, entry):
        if entry['type'] == 'static':
            return self.STATIC_TEMPLATE % entry

        elif entry['type'] == 'fcgi':
            socket_uri = entry['socket']
            if socket_uri.startswith('tcp://'):
                socket = socket_uri[len('tcp://'):]
            elif socket_uri.startswith('unix:///'):
                socket = 'unix:' + socket_uri[len('unix://'):]
            else:
                raise ValueError("Can't parse socket %r" % socket_uri)
            return self.FCGI_TEMPLATE % dict(entry,
                    socket=socket,
                    fcgi_params_path=self.fcgi_params_path)

        elif entry['type'] == 'proxy':
            return self.PROXY_TEMPLATE % entry

        else:
            raise NotImplementedError


class NginxPlugin(object):
    """ Generates a configuration file for each deployment based on its urlmap.
    Upon activation of a new deployment version, the new nginx configuration is
    written, and nginx is reloaded. """

    def __init__(self, sarge):
        self.sarge = sarge
        signals.instance_configuring.connect(self.configure_instance, sarge)
        signals.sarge_initializing.connect(self.initialize, sarge)
        signals.instance_will_be_destroyed.connect(self.destroy, sarge)

    @property
    def etc_nginx(self):
        return self.sarge.home_path / 'etc' / 'nginx'

    def initialize(self, sarge):
        if not self.etc_nginx.isdir():
            (self.etc_nginx).makedirs()
        sarge_sites_conf = self.etc_nginx / 'sarge_sites.conf'
        if not sarge_sites_conf.isfile():
            log.debug("Writing \"sarge_sites\" "
                      "nginx configuration at %r.",
                      sarge_sites_conf)
            sarge_sites_conf.write_text('include %s/*;\n' % self.etc_nginx)
        self.etc_nginx.makedirs_p()

    def _conf_site_path(self, instance):
        return self.etc_nginx / (instance.id_ + '-site')

    def _conf_urlmap_path(self, instance):
        return self.etc_nginx / (instance.id_ + '-urlmap')

    def configure_instance(self, sarge, instance, appcfg, **extra):
        self.etc_nginx.makedirs_p()
        conf_path = self._conf_site_path(instance)
        urlmap_path = self._conf_urlmap_path(instance)

        log.debug("Writing nginx configuration for instance %r at %r.",
                  instance.id_, conf_path)

        conf_options = ""
        nginx_options = instance.config.get('nginx_options', {})
        for key, value in sorted(nginx_options.items()):
            conf_options += '  %s %s;\n' % (key, value)

        conf_urlmap = ""

        for raw_entry in instance.config.get('urlmap', []):
            log.debug("urlmap entry: %r", raw_entry)

            entry = interpolate_config(raw_entry, appcfg)

            if entry['type'] == 'static':
                entry['folder'] = instance.folder

            elif entry['type'] == 'wsgi':
                instance.config['tmp-wsgi-app'] = entry['app_factory']
                entry['socket_path'] = instance.run_folder / 'wsgi-app.sock'

            elif entry['type'] == 'php':
                entry['socket_path'] = instance.run_folder / 'php.sock'

            conf_urlmap += NginxConfGenerator().route(entry)

        with open(conf_path, 'wb') as f:
            f.write('server {\n')
            f.write(conf_options)
            f.write('  include %s;\n' % urlmap_path)
            f.write('}\n')

        with open(urlmap_path, 'wb') as f:
            f.write(conf_urlmap)

    def destroy(self, sarge, instance, **extra):
        self._conf_site_path(instance).unlink_p()
        self._conf_urlmap_path(instance).unlink_p()
