from dataclasses import dataclass
import logging
from typing import Awaitable, Mapping, Tuple, Type, TypeVar
#-
from scrapy import Spider, signals
from scrapy.core.downloader.handlers.http import HTTPDownloadHandler
from scrapy.crawler import Crawler
from scrapy.http import Request, Response
from scrapy.responsetypes import responsetypes
from scrapy.settings import Settings
from scrapy.utils.defer import deferred_from_coro
from scrapy.utils.reactor import verify_installed_reactor
from selenium import webdriver
from twisted.internet.defer import Deferred
#-
from .webdriver import WebDriver

DEFAULT_BROWSER_NAME = 'chrome'
DEFAULT_CONTEXT_NAME = 'default'
PERSISTENT_CONTEXT_PATH_KEY = 'user_data_dir'

DownloadHandler = TypeVar('DownloadHandler', bound='ScrapyDownloadHandler')

_logger = logging.getLogger(__name__)


@dataclass
class Config:
    browser_name: str
    grid_url: str
    implicit_wait_insec: int

    @classmethod
    def from_settings(cls, settings: Settings) -> "Config":
        cfg = cls(
            browser_name=settings.get('SELENIUM_GRID_BROWSER_NAME') \
                    or DEFAULT_BROWSER_NAME,
            grid_url=settings.get('SELENIUM_GRID_URL') or 'http://127.0.0.1:4444',
            implicit_wait_insec=settings.get('SELENIUM_GRID_IMPLICIT_WAIT_INSEC') \
                    or 0,
        )
        return cfg


class ScrapyDownloadHandler(HTTPDownloadHandler):

    config: Config = None
    drivers: Mapping[Tuple[str, str], WebDriver] = None

    def __init__(self, crawler: Crawler) -> None:
        super().__init__(settings=crawler.settings, crawler=crawler)
        verify_installed_reactor(
                'twisted.internet.asyncioreactor.AsyncioSelectorReactor')
        crawler.signals.connect(self.engine_stopped, signals.engine_stopped)
        self.stats = crawler.stats

        self.config = Config.from_settings(crawler.settings)
        self.drivers = {}


    @classmethod
    def from_crawler(cls: Type[DownloadHandler], crawler: Crawler) \
            -> DownloadHandler:
        return cls(crawler)


    def download_request(self, request: Request, spider: Spider) -> Deferred:
        if request.meta.get('selenium_grid'):
            return deferred_from_coro(self._download_request(request, spider))
        return super().download_request(request, spider)


    async def _download_request(self, request: Request, spider: Spider) \
            -> Awaitable[Response]:
        driver = request.meta.get('selenium_grid_driver')
        if not driver:
            browser_name = request.meta.get('selenium_grid_browser',
                    self.config.browser_name)
            context_name = request.meta.get('selenium_grid_context',
                    DEFAULT_CONTEXT_NAME)
            driver = self.drivers.get((browser_name, context_name))
            if not driver:
                driver = await self._create_webdriver(browser_name)
                self.drivers[(browser_name, context_name)] = driver
            request.meta['selenium_grid_driver'] = driver

        implicit_wait_insec = request.meta.get('selenium_grid_implicit_wait_insec',
                self.config.implicit_wait_insec)
        await driver.implicitly_wait(implicit_wait_insec)

        await driver.get(request.url)
        body = await driver.execute_script(
                'return document.documentElement.outerHTML')
        respcls = responsetypes.from_args(
                url=request.url,
                #headers=headers,
                body=body)
        return respcls(
                url=request.url,
                #status=200,
                #headers=headers,
                body=body,
                request=request,
                #ip_address=server_ip_address,
                encoding='utf-8',
                flags=['selenium_grid'])


    async def _create_webdriver(self, browser_name: str):
        if browser_name == 'chrome':
            driver_options = webdriver.ChromeOptions()
        elif browser_name == 'edge':
            driver_options = webdriver.EdgeOptions()
        elif browser_name == 'firefox':
            driver_options = webdriver.FirefoxOptions()
        elif browser_name == 'ie':
            driver_options = webdriver.IeOptions()
        elif browser_name == 'safari':
            driver_options = webdriver.SafariOptions()
        else:
            raise RuntimeError(f"Unknown browser name: {browser_name}")

        return await WebDriver.create(
                command_executor=self.config.grid_url,
                options=driver_options)


    async def engine_stopped(self):
        for driver in self.drivers.values():
            await driver.quit()
