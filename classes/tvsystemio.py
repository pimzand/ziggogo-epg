"""
ZiggoGo EPG

TVSystemIo classes that handle interaction with TvHeadend or simple disk files.
"""

import logging
import requests
import socket

from requests.auth import HTTPBasicAuth, HTTPDigestAuth
from typing import List


class TVSystemIoException(Exception):
    """Failure interacting with TV system"""


class TVSystemIo:
    """Base class used for getting the channel list and writing out the EPG"""

    def get_channel_list(self) -> List[str]:
        """Get the list of channels to grab the EPG for"""
        raise NotImplementedError()

    def write_xmltv(self, data: bytes):
        """Write the XMLTV EPG to storage"""
        raise NotImplementedError()


class TVHeadendIo(TVSystemIo):
    """Class used to interact with TVHeadend for the EPG"""

    DEFAULT_XMLTV_SOCKET_PATH = "/home/hts/.hts/tvheadend/epggrab/xmltv.sock"

    def __init__(
        self,
        host="localhost",
        port=9981,
        username="",
        password="",
        xmltv_socket_path=None,
        network=None,
    ):
        """
        Initialize the TVHeadendIo class

        :param xmltv_socket_path: Path to the xmltv socket of TVHeadend. If None, the path is requested from the
                                  TVHeadend API, falling back to DEFAULT_XMLTV_SOCKET_PATH if that fails.
        :param network: If given, get_channel_list only returns channels that have at least one service on the
                        network with this name (compared case-insensitively).
        """
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._xmltv_socket_path = xmltv_socket_path
        self._network = network

    def _api_get(self, path, params=None):
        """Perform a GET request on the TVHeadend API and return the decoded JSON response"""
        url = f"http://{self._host}:{self._port}/api/{path}"
        try:
            r = requests.get(url, params=params, auth=HTTPBasicAuth(username=self._username, password=self._password))
            if r.status_code == 401:
                # Also try Digest authentication
                r.close()
                r = requests.get(url, params=params, auth=HTTPDigestAuth(username=self._username, password=self._password))
        except requests.ConnectionError:
            raise TVSystemIoException(f"Could not connect to TVHeadend on http://{self._host}:{self._port}.")

        if r.status_code != 200:
            raise TVSystemIoException(f"Error calling TVHeadend api '{path}'. The status code was: {r.status_code}")

        try:
            return r.json()
        except requests.exceptions.JSONDecodeError:
            raise TVSystemIoException(f"Error calling TVHeadend api '{path}'. The response was not valid JSON data.")

    def get_channel_list(self) -> List[str]:
        """Get the list of channels from TVHeadend"""
        if self._network is None:
            logging.info("Requesting known channel list from TVHeadend...")
            channeldata = self._api_get("channel/list")
            try:
                return [channel["val"] for channel in channeldata["entries"]]
            except KeyError:
                raise TVSystemIoException(f"Error getting channel list from TVHeadend. The list was not structured properly.")

        logging.info(f"Requesting known channel list for network '{self._network}' from TVHeadend...")
        servicedata = self._api_get("mpegts/service/grid", params={"limit": 999999, "list": "network"})
        channeldata = self._api_get("channel/grid", params={"limit": 999999, "list": "enabled,name,services"})

        network = self._network.lower()
        try:
            network_services = {
                service["uuid"] for service in servicedata["entries"] if service.get("network", "").lower() == network
            }
            channellist = [
                channel["name"]
                for channel in channeldata["entries"]
                if channel.get("enabled") and not network_services.isdisjoint(channel.get("services", []))
            ]
        except KeyError:
            raise TVSystemIoException(f"Error getting channel list from TVHeadend. The list was not structured properly.")

        if not channellist:
            logging.warning(f"No channels found on a network named '{self._network}'.")
        return channellist

    def _discover_xmltv_socket(self) -> str:
        """
        Ask TVHeadend for the socket path of the external XMLTV grabber module.

        Falls back to DEFAULT_XMLTV_SOCKET_PATH if the path cannot be determined (for example because the
        configured user has no admin rights on the TVHeadend API).
        """
        try:
            moduledata = self._api_get("idnode/load", params={"class": "epggrab_mod_ext"})
            for module in moduledata.get("entries", []):
                params = {param.get("id"): param.get("value") for param in module.get("params", [])}
                if params.get("path"):
                    logging.info(f"TVHeadend reports the xmltv socket at '{params['path']}'.")
                    return params["path"]
        except TVSystemIoException as ex:
            logging.warning(str(ex))

        logging.info(
            f"Could not determine the xmltv socket path from the TVHeadend API, "
            f"using '{self.DEFAULT_XMLTV_SOCKET_PATH}'."
        )
        return self.DEFAULT_XMLTV_SOCKET_PATH

    def write_xmltv(self, data: bytes):
        """Write the XMLTV EPG to TVHeadend directly"""
        socket_path = self._xmltv_socket_path
        if socket_path is None:
            socket_path = self._discover_xmltv_socket()

        logging.info("Writing XMLTV directly to TVHeadend...")
        try:
            sock = socket.socket(socket.AF_UNIX)
            try:
                sock.connect(socket_path)
                sock.sendall(data)
            finally:
                sock.close()

        except OSError:
            raise TVSystemIoException(
                f"Error writing XMLTV to '{socket_path}'. Is the path correct, "
                f"is TVHeadend running and was the XMLTV EPG grabber enabled?"
            )


class XMLTVFileIo(TVSystemIo):
    """Class used to interact with files on disk for the EPG"""

    def __init__(self, channel_list_filename="channels.txt", xmltv_filename="ziggogo.xml"):
        """Initialize the XMLTVFileIo class"""
        self._channel_list_filename = channel_list_filename
        self._xmltv_filename = xmltv_filename

    def get_channel_list(self) -> List[str]:
        """Get the list of channels from the channel list file"""
        logging.info(f"Reading known channel list from '{self._channel_list_filename}'...")

        try:
            with open(self._channel_list_filename, "rb") as f:
                channellist = []
                for line in f:
                    channel = line.decode("utf-8").strip()
                    if channel:
                        channellist.append(channel)

        except OSError:
            raise TVSystemIoException(f"Error reading '{self._channel_list_filename}'. Does the file exist and is it readable?")

        return channellist

    def write_xmltv(self, data: bytes):
        """Write the XMLTV EPG to file"""
        logging.info(f"Writing XMLTV to '{self._xmltv_filename}'...")

        try:
            with open(self._xmltv_filename, "wb") as f:
                f.write(data)

        except OSError:
            raise TVSystemIoException(f"Error writing XMLTV to '{self._xmltv_filename}'. Is the path correct and is it writable?")


class ChannelFileIo(XMLTVFileIo):
    """Class used to only write XMLTV file and take a manually defined channel list"""

    def __init__(self, channels: List, xmltv_filename="ziggogo.xml"):
        """Initialize the ChannelFileIo class"""
        self._channel_list = channels
        self._xmltv_filename = xmltv_filename

    def get_channel_list(self) -> List[str]:
        """Get the list of channels from the channel list file"""
        return [channel.strip() for channel in self._channel_list]
