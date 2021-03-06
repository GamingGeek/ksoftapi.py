# -*- coding: utf-8 -*-
import asyncio
import logging
import time
import traceback
from urllib.parse import quote

from .data_objects import Image, RedditImage, TagCollection, WikiHowImage, Ban, BanIterator, LyricsSearch, Artist, Track, Album
from .errors import APIError
from .events import BanEvent, UnBanEvent
from .http import krequest, Route

logger = logging.getLogger()


class Client:
    """
    .. _aiohttp session: https://aiohttp.readthedocs.io/en/stable/client_reference.html#client-session

    Client object for KSOFT.SI API

    This is a client object for KSoft.Si API. Here are two versions. Basic without discord.py bot
    and a pluggable version that inserts this client object directly into your discord.py bot.


    Represents a client connection that connects to ksoft.si. It works in two modes:
        1. As a standalone variable.
        2. Plugged-in to discord.py Bot or AutoShardedBot, see :any:`Client.pluggable`

    Parameters
    -------------
    api_key: :class:`str`
        Your ksoft.si api token.
        Specify different base url.
    **bot: Bot or AutoShardedBot
        Your bot client from discord.py
    **loop: asyncio loop
        Your asyncio loop.
    **low_memory: bool[Optional]
        Low memory mode, save images to files instead of memory. WIP

    """

    def __init__(self, api_key: str, bot=None, loop=asyncio.get_event_loop(), **kwargs):
        self.api_key = api_key
        self._loop = loop
        self.http = krequest(global_headers=[
            ("Authorization", f"Bearer {self.api_key}")
        ], loop=self._loop, lowmem=kwargs.get("lowmem_mode"))
        self.bot = bot

        self._ban_hook = []
        self._last_update = time.time() - 60 * 10

        if self.bot is not None:
            self.bot.loop.create_task(self._ban_updater)

        logger_string = str("NANI") + self.api_key[-4:].rjust(len(self.api_key), "*")
        logger.info(f"KSOFT API Logging in as {logger_string}")

    def register_ban_hook(self, func):
        if func not in self._ban_hook:
            logger.info(f"Registered event hook {func.__name__}")
            self._ban_hook.append(func)

    def unregister_ban_hook(self, func):
        if func in self._ban_hook:
            logger.info(f"Unregistered event hook {func.__name__}")
            self._ban_hook.remove(func)

    async def _dispatch_ban_event(self, event):
        logger.info('Dispatching event of type %s to %d hooks', event.__class__.__name__, len(self._ban_hook))
        for hook in self._ban_hook:
            await hook(event)

    async def _ban_updater(self):
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            try:
                if self._ban_hook:
                    r = await self.http.request(Route.bans("GET", "/updates"), params={"timestamp": self._last_update})
                    self._last_update = time.time()
                    for b in r['data']:
                        if b['active'] is True:
                            await self._dispatch_ban_event(BanEvent(**b))
                        else:
                            await self._dispatch_ban_event(UnBanEvent(**b))
            except Exception as e:
                logger.error("Error in the ban update loop: %s" % e)
                traceback.print_exc()
            finally:
                await asyncio.sleep(60 * 5)

    @classmethod
    def pluggable(cls, bot, api_key: str, *args, **kwargs):
        """
        Pluggable version of Client. Inserts Client directly into your Bot client.
        Called by using `bot.ksoft`


        Parameters
        -------------
        bot: discord.ext.commands.Bot or discord.ext.commands.AutoShardedBot
            Your bot client from discord.py
        api_key: :class:`str`
            Your ksoft.si api token.


        .. note::
            Takes the same parameters as :class:`Client` class.
            Usage changes to ``bot.ksoft``. (``bot`` is your bot client variable)

        """
        try:
            return bot.ksoft
        except AttributeError:
            bot.ksoft = cls(api_key, bot=bot, *args, **kwargs)
            return bot.ksoft

    async def random_image(self, tag: str, nsfw: bool = False) -> Image:
        """|coro|

        This function gets a random image from the specified tag.

        Parameters
        ------------
        tag: :class:`str`
            Image tag from string.
        nsfw: :class:`bool`
            If to display NSFW images.


        :return: :class:`ksoftapi.data_objects.Image`

        """
        g = await self.http.request(Route.meme("GET", "/random-image"), params={"tag": tag, "nsfw": str(nsfw)})
        return Image(**g)

    async def random_meme(self) -> RedditImage:
        """|coro|

        This function gets a random meme from multiple sources from reddit.



        :return: :class:`ksoftapi.data_objects.RedditImage`

        """
        g = await self.http.request(Route.meme("GET", "/random-meme"))
        return RedditImage(**g)

    async def random_aww(self) -> RedditImage:
        """|coro|

        This function gets a random cute pictures from multiple sources from reddit.



        :return: :class:`ksoftapi.data_objects.RedditImage`

        """
        g = await self.http.request(Route.meme("GET", "/random-aww"))
        return RedditImage(**g)

    async def random_wikihow(self) -> WikiHowImage:
        """|coro|

        This function gets a random WikiHow image.



        :return: :class:`ksoftapi.data_objects.WikiHowImage`

        """
        g = await self.http.request(Route.meme("GET", "/random-wikihow"))
        return WikiHowImage(**g)

    async def random_reddit(self, subreddit: str) -> RedditImage:
        """|coro|

        This function gets a random post from specified subreddit.



        :return: :class:`ksoftapi.data_objects.RedditImage`

        """
        g = await self.http.request(Route.meme("GET", "/rand-reddit/{subreddit}", subreddit=subreddit))
        return RedditImage(**g)

    async def tags(self) -> TagCollection:
        """|coro|

        This function gets all available tags on the api.



        :return: :class:`ksoftapi.data_objects.TagCollection`

        """
        g = await self.http.request(Route.meme("GET", "/tags"))
        return TagCollection(**g)

    # BANS
    async def bans_add(self, user_id: int, reason: str, proof: str, **kwargs):
        arg_params = ["mod", "user_name", "user_discriminator", "appeal_possible"]
        data = {
            "user": user_id,
            "reason": reason,
            "proof": proof
        }
        for arg, val in kwargs.items():
            if arg in arg_params:
                data.update({arg: val})
            else:
                raise ValueError(f"unknown parameter: {arg}")
        r = await self.http.request(Route.bans("POST", "/add"), data=data)
        if r.get("success", False) is True:
            return True
        else:
            raise APIError(**r)

    async def bans_check(self, user_id: int) -> bool:
        r = await self.http.request(Route.bans("GET", "/check"), params={"user": user_id})
        if r.get("is_banned", None) is not None:
            return r['is_banned']
        else:
            raise APIError(**r)

    async def bans_info(self, user_id: int) -> Ban:
        r = await self.http.request(Route.bans("GET", "/info"), params={"user": user_id})
        if r.get("is_ban_active", None) is not None:
            return Ban(**r)
        else:
            raise APIError(**r)

    async def bans_remove(self, user_id: int) -> bool:
        r = await self.http.request(Route.bans("DELETE", "/remove"), params={"user": user_id})
        if r.get("done", None) is not None:
            return True
        else:
            raise APIError(**r)

    def ban_get_list_iterator(self):
        return BanIterator(self, Route.bans("GET", "/list"))

    async def lyrics_search(self, query: str, **kwargs) -> LyricsSearch:
        """|coro|

        This function gets lyrics from a search query.



        :return: :class:`ksoftapi.data_objects.LyricsSearch`

        """
        arg_params = ["text_only", "limit"]
        data = {
            "q": quote(query)
        }
        for arg, val in kwargs.items():
            if arg in arg_params:
                data.update({arg: val})
            else:
                raise ValueError(f"unknown parameter: {arg}")
        r = await self.http.request(Route.lyrics("GET", "/search"), params=data)
        return LyricsSearch(**r)

    async def lyrics_artist(self, identifier: int) -> Artist:
        """|coro|

        This function gets an artist from an id.



        :return: :class:`ksoftapi.data_objects.Artist`

        """
        r = await self.http.request(Route.lyrics("GET", f"/artist/{identifier}"))
        return Artist(**r)

    async def lyrics_album(self, identifier: int) -> Album:
        """|coro|

        This function gets an album from an id.



        :return: :class:`ksoftapi.data_objects.Album`

        """
        r = await self.http.request(Route.lyrics("GET", f"/album/{identifier}"))
        return Album(**r)

    async def lyrics_track(self, identifier: int) -> Track:
        """|coro|

        This function gets a track from an id.



        :return: :class:`ksoftapi.data_objects.Track`

        """
        r = await self.http.request(Route.lyrics("GET", f"/track/{identifier}"))
        return Track(**r)

