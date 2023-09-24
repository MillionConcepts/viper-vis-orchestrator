"""
utilities for managed execution of the yamcs server and interpretation of its
outputs. intended to aid extraction of parameters for testing.
"""

import atexit
from io import FileIO
from pathlib import Path
import re
import socket
import struct
import time
from typing import Literal, Union
import warnings

from cytoolz import first
from hostess.directory import index_breadth_first
from hostess.subutils import Viewer
import requests
from requests.exceptions import HTTPError, ConnectionError

from bitstruct import BitStruct

# on packet format: see https://public.ccsds.org/Pubs/133x0b2e1.pdf
YAMCS_PACKET_HEADER_FORMAT = ">3H"
YAMCS_PACKET_TIME_FORMAT = ">IH"
# struct object for parsing 2-octet segments from packet primary header
HSTRUCT = struct.Struct(YAMCS_PACKET_HEADER_FORMAT)
# struct object for parsing 6-byte integer/fraction timestamp from packet body
TSTRUCT = struct.Struct(YAMCS_PACKET_TIME_FORMAT)
# bit field specifications for first two segments of packet primary header
HEADER_SPEC_1 = {'pvn': 3, 'type': 1, 'secflag': 1, 'apid': 11}
HEADER_SPEC_2 = {'seqflag': 2, 'seqcount': 14}
BBLOCK_1, BBLOCK_2 = map(BitStruct, (HEADER_SPEC_1, HEADER_SPEC_2))

# one of likely many endpoints that will ready the server to receive packets
TCP_MODE_ENDPOINT = "yamcs/api/links/viper/tcp-tm-wallclocktime"
TOGGLE = Literal["enable", "disable"]
DEFAULT_TCP_PORT = 18203
DEFAULT_HTTP_PORT = 8090


def find_yamcsd() -> str:
    """look for yamcs server daemon binary in local tree"""
    roots = [
        d for d in Path(__file__).parent.iterdir()
        if d.name.startswith("viper-") and d.is_dir()
    ]
    for root in roots:
        files = index_breadth_first(root)
        try:
            return first(
                filter(lambda x: x['path'].endswith('yamcsd'), files)
            )['path']
        except StopIteration:
            continue
    raise FileNotFoundError


def toggle_yamcsd_tcp(
    port: int = DEFAULT_HTTP_PORT,
    endpoint: str = TCP_MODE_ENDPOINT,
    command: TOGGLE = "enable"
) -> str:
    """toggle the tcp-tm-wallclocktime mode of a running yamcsd server"""
    url = f"http://localhost:{port}/{endpoint}:{command}"
    response = requests.post(url)
    response.raise_for_status()
    return response.text


def run_yamcs_server(*command_args, enable_tcp=True, max_retries=5) -> Viewer:
    """
    launch the yamcs server. returns a hostess.Viewer object in background
    mode that can be used to monitor stdout/stderr, terminate the process, etc.
    """
    yamcs_server_process = Viewer.from_command(
        find_yamcsd(), *command_args, _bg=True,
    )
    atexit.register(yamcs_server_process.terminate)
    if enable_tcp is True:
        retries, ok, exception = 0, False, None
        for _ in range(max_retries):
            try:
                time.sleep(1.5)
                ok = toggle_yamcsd_tcp()
                break
            except (HTTPError, ConnectionError) as err:
                exception = err
        if ok is False:
            warnings.warn(f"yamcs tcp instruction failed: {exception}")
    return yamcs_server_process


def parse_header(headerbytes: bytes) -> dict[str, Union[int, bytes]]:
    """parse header portion of yamcs packet"""
    b1, b2, length = HSTRUCT.unpack(headerbytes)
    parsed = {'length': length + 1} | BBLOCK_1.unpack(b1) | BBLOCK_2.unpack(b2)
    return parsed | {'content': headerbytes}  # bytes at the end because ugly


def parse_time(timebytes: bytes) -> float:
    """parse yamcs packet timestamp (first 6 bytes of body)"""
    integer, fraction = TSTRUCT.unpack(timebytes)
    return integer + fraction / 2**16


def read_packet(stream: FileIO) -> dict[str, Union[float, bytes, dict]]:
    """
    read the next packet from a FileIO object mapped to a .raw packet file
    """
    header = parse_header(stream.read(HSTRUCT.size))
    body = stream.read(header['length'])
    timestamp = parse_time(body[:TSTRUCT.size])
    return {'time': timestamp, 'header': header, 'body': body}


def serve_packet(sock: socket.socket, packet: dict) -> int:
    return sock.send(packet['header']['content'] + packet['body'])


def open_yamcs_socket(port=DEFAULT_TCP_PORT, host='localhost'):
    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    server_sock.bind((host, port))
    server_sock.listen(1)
    tcp_sock, addr = server_sock.accept()
    return tcp_sock


def get_yamcsd_url(viewer: Viewer, retries=5, delay=1.5) -> str:
    """get root HTTP url from yamcsd output, as supplied by a hostess Viewer"""
    for _ in range(retries):
        # note that yamcsd prints to stderr by default
        try:
            rmap = map(lambda e: re.search(r"http://(.*yamcs)", e), viewer.err)
            return next(filter(None, rmap)).group(1)
        except StopIteration:
            time.sleep(delay)
            continue
    raise TimeoutError
