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

from typing import Awaitable
from typing import Optional
from typing import Union
#-
from selenium.common.exceptions import NoSuchElementException
from selenium.common.exceptions import NoSuchFrameException
from selenium.common.exceptions import NoSuchWindowException
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.command import Command
#-
from .common.alert import Alert
from .webelement import WebElement


class SwitchTo:
    def __init__(self, driver) -> None:
        import weakref

        self._driver = weakref.proxy(driver)


    @property
    async def active_element(self) -> Awaitable[WebElement]:
        """Returns the element with focus, or BODY if nothing has focus.

        :Usage:
            ::

                element = driver.switch_to.active_element
        """
        return await self._driver.execute(Command.W3C_GET_ACTIVE_ELEMENT)["value"]


    @property
    async def alert(self) -> Awaitable[Alert]:
        """Switches focus to an alert on the page.

        :Usage:
            ::

                alert = driver.switch_to.alert
        """
        alert = Alert(self._driver)
        _ = await alert.text
        return alert


    async def default_content(self) -> Awaitable[None]:
        """Switch focus to the default frame.

        :Usage:
            ::

                driver.switch_to.default_content()
        """
        await self._driver.execute(Command.SWITCH_TO_FRAME, {"id": None})


    async def frame(self, frame_reference: Union[str, int, WebElement]) \
            -> Awaitable[None]:
        """Switches focus to the specified frame, by index, name, or
        webelement.

        :Args:
         - frame_reference: The name of the window to switch to, an integer representing the index,
                            or a webelement that is an (i)frame to switch to.

        :Usage:
            ::

                driver.switch_to.frame('frame_name')
                driver.switch_to.frame(1)
                driver.switch_to.frame(driver.find_elements(By.TAG_NAME, "iframe")[0])
        """
        if isinstance(frame_reference, str):
            try:
                frame_reference = await self._driver.find_element(By.ID,
                        frame_reference)
            except NoSuchElementException:
                try:
                    frame_reference = await self._driver.find_element(By.NAME,
                            frame_reference)
                except NoSuchElementException as exc:
                    raise NoSuchFrameException(frame_reference) from exc

        await self._driver.execute(Command.SWITCH_TO_FRAME, {"id": frame_reference})


    async def new_window(self, type_hint: Optional[str] = None) -> Awaitable[None]:
        """Switches to a new top-level browsing context.

        The type hint can be one of "tab" or "window". If not specified the
        browser will automatically select it.

        :Usage:
            ::

                driver.switch_to.new_window('tab')
        """
        value = await self._driver.execute(Command.NEW_WINDOW,
                {"type": type_hint})["value"]
        await self._w3c_window(value["handle"])


    async def parent_frame(self) -> Awaitable[None]:
        """Switches focus to the parent context. If the current context is the
        top level browsing context, the context remains unchanged.

        :Usage:
            ::

                driver.switch_to.parent_frame()
        """
        await self._driver.execute(Command.SWITCH_TO_PARENT_FRAME)


    async def window(self, window_name: str) -> Awaitable[None]:
        """Switches focus to the specified window.

        :Args:
         - window_name: The name or window handle of the window to switch to.

        :Usage:
            ::

                driver.switch_to.window('main')
        """
        await self._w3c_window(window_name)


    async def _w3c_window(self, window_name: str) -> Awaitable[None]:
        async def send_handle(h):
            await self._driver.execute(Command.SWITCH_TO_WINDOW, {"handle": h})

        try:
            # Try using it as a handle first.
            await send_handle(window_name)
        except NoSuchWindowException:
            # Check every window to try to find the given window name.
            original_handle = await self._driver.current_window_handle
            handles = await self._driver.window_handles
            for handle in handles:
                await send_handle(handle)
                current_name = await self._driver.execute_script(
                        "return window.name")
                if window_name == current_name:
                    return
            await send_handle(original_handle)
            raise
