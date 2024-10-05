# Licensed to the Software Freedom Conservancy (SFC) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The SFC licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.

from selenium.webdriver.remote.command import Command
from selenium.webdriver.remote.mobile import _ConnectionType

class Mobile:
    ConnectionType = _ConnectionType
    ALL_NETWORK = ConnectionType(6)
    WIFI_NETWORK = ConnectionType(2)
    DATA_NETWORK = ConnectionType(4)
    AIRPLANE_MODE = ConnectionType(1)

    def __init__(self, driver):
        import weakref

        self._driver = weakref.proxy(driver)


    @property
    async def network_connection(self):
        return self.ConnectionType(await self._driver.execute(
                Command.GET_NETWORK_CONNECTION) \
                ["value"])


    async def set_network_connection(self, network):
        """Set the network connection for the remote device.

        Example of setting airplane mode::

            driver.mobile.set_network_connection(driver.mobile.AIRPLANE_MODE)
        """
        mode = network.mask if isinstance(network, self.ConnectionType) else network
        return self.ConnectionType(await self._driver.execute(
                Command.SET_NETWORK_CONNECTION,
                {"name": "network_connection", "parameters": {"type": mode}}) \
                ["value"])


    @property
    async def context(self):
        """Returns the current context (Native or WebView)."""
        return await self._driver.execute(Command.CURRENT_CONTEXT_HANDLE)


    @context.setter
    async def context(self, new_context) -> None:
        """Sets the current context."""
        await self._driver.execute(Command.SWITCH_TO_CONTEXT, {"name": new_context})


    @property
    async def contexts(self):
        """Returns a list of available contexts."""
        return await self._driver.execute(Command.CONTEXT_HANDLES)
