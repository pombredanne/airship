import json
from path import path
from mock import Mock, call
from common import SargeTestCase, imp


mock_plugin = Mock()


class PluginApiTest(SargeTestCase):

    def sarge(self):
        return imp('sarge').Sarge({'home': self.tmp,
                                   'plugins': [__name__ + ':mock_plugin']})

    def test_plugin_named_in_config_file_gets_called(self):
        mock_plugin.reset_mock()
        s = self.sarge()
        self.assertEqual(mock_plugin.mock_calls, [call(s)])

    def test_subscribe_to_activation_event(self):
        mock_handler = Mock(im_self=None)
        sarge = self.sarge()
        sarge.on_activate_version.connect(mock_handler)
        sarge.new_instance().start()
        self.assertEqual(len(mock_handler.mock_calls), 1)

    def test_activation_event_passes_shared_dict(self):
        sarge = self.sarge()

        def handler1(depl, share, **extra):
            share['test-something'] = 123

        got = []

        def handler2(depl, share, **extra):
            got.append(share.get('test-something'))

        sarge.on_activate_version.connect(handler1)
        sarge.on_activate_version.connect(handler2)

        instance = sarge.new_instance()
        instance.start()
        self.assertEqual(got, [123])

    def test_activation_event_allows_passing_info_to_application(self):
        def handler(depl, appcfg, **extra):
            appcfg['your-order'] = "is here"

        sarge = self.sarge()
        sarge.on_activate_version.connect(handler)

        instance = sarge.new_instance()
        instance.start()

        cfg_folder = path(instance.folder + '.cfg')
        with (cfg_folder / imp('sarge.core').APP_CFG).open() as f:
            appcfg = json.load(f)
        self.assertEqual(appcfg['your-order'], "is here")
