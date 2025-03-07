"""
Defines a thread class for reading the can bus using python-can library.
Messages are put into queue for usage outside this thread.

Thanks goes to the contributors of https://github.com/linuxkidd/rvc-monitor-py
This code is derived from parts of https://github.com/linuxkidd/rvc-monitor-py/blob/master/usr/bin/rvc2mqtt.py
which was licensed using Apache-2.0.  No copyright information was present in the above mentioned file but original
content is owned by the authors. 

Copyright 2022 Sean Brogan
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

import threading
import can
import logging
import queue

class CAN_Watcher(threading.Thread):
    def __init__(self, interface, rx_queue: queue.Queue, tx_queue: queue.Queue):
        threading.Thread.__init__(self)
        # A flag to notify the thread that it should finish up and exit
        self.kill_received = False
        self.Logger = logging.getLogger(__name__)
        self.Logger.info(f"Starting can bus on interface {interface}")
        self.bus = can.interface.Bus(channel=interface, interface="socketcan")
        self.rx = rx_queue
        self.tx = tx_queue

    def run(self):
        while not self.kill_received:
            message = self.bus.recv(.25)  # read messages from a canbus
            if message is not None and not message.is_error_frame:
                self.rx.put(message)  # Put message into queue

            if not self.tx.empty():   # pending message to send
                msg_dict = self.tx.get() # pull from queue
                try:
                    tx_message = can.Message(arbitration_id=msg_dict["arbitration_id"], data=msg_dict["data"], is_extended_id=True)
                    self.bus.send(tx_message, 1)  # send on canbus
                except Exception as e:
                    self.Logger.error(f"Exception trying to send {e}")
                    self.Logger.debug(f"Failed Msg: {str(tx_message)}")
                
