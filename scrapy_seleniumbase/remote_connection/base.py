import asyncio
import logging
import ssl
import string
from urllib import parse
#-
import aiohttp
from aiohttp_socks import ProxyConnector
from selenium.webdriver.remote import utils
from selenium.webdriver.remote.errorhandler import ErrorCode
from selenium.webdriver.remote.remote_connection import (
        RemoteConnection as BaseRemoteConnection,)

_logger = logging.getLogger(__name__)

class RemoteConnection(BaseRemoteConnection):
    """Async connection to Selenium Hub
    """
    def _get_connection_manager(self):
        init_args = {'timeout': self.get_timeout()}
        if self._proxy_url:
            init_args['connector'] = ProxyConnector.from_url(self._proxy_url)
        return aiohttp.ClientSession(**init_args)


    async def _request(self, method, url, body=None):
        """Send an HTTP request to the remote server.

        :Args:
         - method - A string for the HTTP method to send the request with.
         - url - A string for the URL to send the request to.
         - body - A string for request body. Ignored unless method is POST or PUT.

        :Returns:
          A dictionary with the server's parsed JSON response.
        """
        parsed_url = parse.urlparse(url)
        headers = self.get_remote_connection_headers(parsed_url, self.keep_alive)
        response = None
        request_args = {'headers': headers}
        if body and method in ("POST", "PUT"):
            request_args['data'] = body
        if self._ca_certs:
            # verify_mode default to CERT_REQUIRED
            request_args['ssl'] = ssl.create_default_context(cafile=self._ca_certs)

        if self.keep_alive:
            response = await self._conn.request(method, url, **request_args)
            statuscode = response.status
        else:
            conn = self._get_connection_manager()
            async with conn as http:
                response = await http.request(method, url, **request_args)
            # graceful shutdown
            await asyncio.sleep(0)
            statuscode = response.status
        data = await response.text()
        _logger.debug("Remote response: status=%s | data=%s | headers=%s",
                response.status, data, response.headers)
        try:
            if 300 <= statuscode < 304:
                return self._request("GET", response.headers.get("location", None))
            if 399 < statuscode <= 500:
                return {"status": statuscode, "value": data}
            content_type = []
            if response.headers.get("Content-Type", None):
                content_type = response.headers.get("Content-Type", None).split(";")
            if not any([x.startswith("image/png") for x in content_type]):
                try:
                    data = utils.load_json(data.strip())
                except ValueError:
                    if 199 < statuscode < 300:
                        status = ErrorCode.SUCCESS
                    else:
                        status = ErrorCode.UNKNOWN_ERROR
                    return {"status": status, "value": data.strip()}

                # Some drivers incorrectly return a response
                # with no 'value' field when they should return null.
                if "value" not in data:
                    data["value"] = None
                return data
            data = {"status": 0, "value": data}
            return data
        finally:
            _logger.debug("Finished Request")
            response.close()


    async def execute(self, command, params):
        """Send a command to the remote server.

        Any path substitutions required for the URL mapped to the command should be
        included in the command parameters.

        :Args:
         - command - A string specifying the command to execute.
         - params - A dictionary of named parameters to send with the command as
           its JSON payload.
        """
        command_info = self._commands[command]
        assert command_info is not None, f"Unrecognised command {command}"
        path_string = command_info[1]
        path = string.Template(path_string).substitute(params)
        substitute_params = {word[1:] for word in path_string.split("/") \
                if word.startswith("$")}  # remove dollar sign
        if isinstance(params, dict) and substitute_params:
            for word in substitute_params:
                del params[word]
        data = utils.dump_json(params)
        url = f'{self._url}{path}'
        trimmed = self._trim_large_entries(params)
        _logger.debug("%s %s %s", command_info[0], url, str(trimmed))
        return await self._request(command_info[0], url, body=data)


    @property
    def closed(self):
        return self._conn.closed


    async def close(self):
        """Clean up resources when finished with the remote_connection
        """
        if not self._conn.closed:
            await self._conn.close()
            # graceful shutdown
            # see: https://docs.aiohttp.org/en/stable/client_advanced.html#graceful-shutdown
            await asyncio.sleep(0.250)
