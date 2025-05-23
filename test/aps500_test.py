"""
Unit tests for the dimmer entity class

Copyright 2025 Dan Berglund
SPDX-License-Identifier: Apache-2.0

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.

"""

import unittest
from unittest.mock import MagicMock
import context  # add rvc2mqtt package to the python path using local reference
from rvc2mqtt.entity.aps500 import DcSystemSensor_DC_SOURCE_STATUS_1 as Aps500

class Test_Aps500(unittest.TestCase):

    def test_basic(self):
        mock = MagicMock()
        mock.mqtt_support.make_device_topic_string.return_value = 'topic_string'
        
        l = Aps500({'instance': 1, 'instance_name': "test aps", 'source_id': '80', 'command_topic': 'aps500/set/', 'status_topic': 'aps500/status/'}, mock)
        self.assertTrue(type(l), Aps500)

if __name__ == '__main__':
    unittest.main()
