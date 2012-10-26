""" Sarge automated installation script
usage: python <(curl -fsSL raw.github.com/mgax/sarge/master/install_sarge.py) path/to/sarge
"""

import os
import sys
import subprocess
import urllib
import json


SARGE_PACKAGE = 'https://github.com/mgax/sarge/tarball/master'
PATH_PY_URL = 'https://raw.github.com/jaraco/path.py/2.3/path.py'
VIRTUALENV_URL = 'https://raw.github.com/pypa/virtualenv/develop/virtualenv.py'
DISTRIBUTE_URL = ('http://pypi.python.org/packages/source/'
                  'd/distribute/distribute-0.6.28.tar.gz')
PIP_URL = 'https://github.com/dholth/pip/zipball/e0f3535'  # wheel_build branch

def install(sarge_home, python_bin):
    username = os.popen('whoami').read().strip()
    virtualenv_path = sarge_home / 'var' / 'sarge-venv'
    virtualenv_bin = virtualenv_path / 'bin'
    sarge_cfg = sarge_home / 'etc' / 'sarge.yaml'

    if not (virtualenv_bin / 'python').isfile():
        import virtualenv
        print "creating virtualenv in {virtualenv_path} ...".format(**locals())
        virtualenv.create_environment(virtualenv_path,
                                      search_dirs=[sarge_home / 'dist'],
                                      use_distribute=True,
                                      never_download=True)

    print "installing sarge ..."
    subprocess.check_call([virtualenv_bin / 'pip', 'install', SARGE_PACKAGE])

    if not sarge_cfg.isfile():
        (sarge_home / 'etc').mkdir_p()
        sarge_cfg.write_bytes(json.dumps({
            'wheel_index_dir': sarge_home / dist}))
        subprocess.check_call([virtualenv_bin / 'sarge', sarge_home, 'init'])

    cmd = "{sarge_home}/bin/supervisord".format(**locals())
    fullcmd = "su {username} -c '{cmd}'".format(**locals())

    print
    print ("Installation complete! Run the following command "
           "on system startup:\n")
    print "  " + fullcmd
    print
    print "To start supervisord now, run this:"
    print
    print "  " + cmd
    print


def download_to(url, file_path):
    print "downloading {url} to {file_path}".format(**locals())
    http = urllib.urlopen(url)
    with open(file_path, 'wb') as f:
        f.write(http.read())
    http.close()


if __name__ == '__main__':
    sarge_home = os.path.abspath(sys.argv[1])
    dist = os.path.join(sarge_home, 'dist')
    if not os.path.isdir(dist):
        os.makedirs(dist)

    download_to(PATH_PY_URL, os.path.join(dist, 'path.py'))
    download_to(VIRTUALENV_URL, os.path.join(dist, 'virtualenv.py'))
    download_to(DISTRIBUTE_URL, os.path.join(dist, 'distribute-0.6.28.tar.gz'))
    download_to(PIP_URL, os.path.join(dist, 'pip-1.2.1.post1.zip'))

    sys.path[0:0] = [dist]
    from path import path
    install(path(sarge_home), sys.executable)