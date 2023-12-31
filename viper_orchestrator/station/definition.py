"""high-level definition of the orchestrator application."""
from pathlib import Path
import random
from typing import Literal

from hostess.station.actors import InstructionFromInfo
from hostess.station.station import Station
from viper_orchestrator.config import (
    DATA_ROOT,
    PARAMETERS,
    LIGHTSTATE_LOG_FILE,
    STATION_LOG_ROOT,
)
from viper_orchestrator.station.components import (
    InsertIntoDatabase,
    process_image_instruction,
    thumbnail_instruction,
    jpeg_instruction,
)


def create_station():
    """creates the station"""
    host, port = "localhost", random.randint(10000, 20000)
    station = Station(host, port, n_threads=12, logdir=STATION_LOG_ROOT)
    # Actor that creates instructions to make image products when it receives
    # an info Message about a new image
    station.add_element(InstructionFromInfo, name="process_image")
    station.process_image_target_name = "image_processor"
    station.process_image_instruction_maker = process_image_instruction
    station.process_image_criteria = (
        lambda msg: msg["event_type"] == "image_published",
    )
    # Actor that performs database inserts for SQLAlchemy DeclarativeBase
    # objects sent by Delegates in completion or info Messages
    station.add_element(InsertIntoDatabase)
    # add Actors that create instructions to make thumbnails and full-res
    # JPEGs when we hear about a new TIFF file
    station.add_element(InstructionFromInfo, name="thumbnail")
    station.add_element(InstructionFromInfo, name="browse")
    station.browse_instruction_maker = jpeg_instruction
    station.thumbnail_instruction_maker = thumbnail_instruction
    browse_attrs = {
        "criteria": [
            lambda n: (
                Path(n["content"]).is_file()
                and Path(n["content"]).name.endswith("tif")
            )
        ],
        "target_name": "browsemaker",
    }
    for proc in ("browse", "thumbnail"):
        for attr, val in browse_attrs.items():
            setattr(station, f"{proc}_{attr}", val)
    return station


def launch_delegates(
    station: Station,
    mock: bool = False,
    processor_path: tuple[str, str] = ("viper", "realtime"),
    yamcs_url="localhost:8090/yamcs",
    update_interval: float = 0.5,
    context: Literal["local", "subprocess", "daemon"] = "daemon",
    n_threads: int = 4,
) -> None:
    """defines, launches, and queues config instructions for delegates"""
    delkwargs = {
        "update_interval": update_interval,
        "context": context,
        "n_threads": n_threads,
    }
    thumbnail_watch_launch_spec = {
        # sensor that watches a directory on the filesystem
        "elements": [("hostess.station.actors", "DirWatch")],
    }
    thumbnail_watch_config_spec = {
        # what directory shall we watch?
        "dirwatch_target": DATA_ROOT,
        # what filename patterns are we watching for?
        "dirwatch_patterns": (r".*\.tif",),
    }
    # browse making is handled by a generic Actor that calls plain
    # functions; the details are specified in Instructions from the Station
    browse_launch_spec = {
        "elements": [("hostess.station.actors", "FuncCaller")]
    }
    # create_image.create()-handling delegate
    station.launch_delegate(
        "image_processor",
        elements=(
            ("viper_orchestrator.station.components", "ImageProcessor"),
        ),
        **delkwargs,
    )
    # to work correctly in mock mode, the parameter-watching delegates must
    # always be in local context so that they can interact with the
    # locally-instantiated MockServer. execution context doesn't matter if
    # they're connecting to a real yamcs server.
    # also note that the server url and processor path are harmlessly ignored
    # in mock mode.
    if mock is True:
        subscriber_kwargs = delkwargs | {"context": "local"}
    else:
        subscriber_kwargs = delkwargs
    # image parameter-watching delegate.
    station.launch_delegate(
        "image_watcher",
        elements=(("viper_orchestrator.station.components", "ImageSensor"),),
        **subscriber_kwargs,
    )
    # light state parameter-watching and handling delegate.
    # unlike images, we encapsulate handling for these parameters in a single
    # Delegate (and a single Sensor attached to that Delegate). see the
    # docstring of viper_orchestrator.station.components.LightSensor for
    # rationale.
    station.launch_delegate(
        "light_watcher",
        elements=(("viper_orchestrator.station.components", "LightSensor"),),
        **subscriber_kwargs,
    )
    # tiff-write-watching delegate. this watches the filesystem for writes
    # performed in the create_image.create() workflow, not yamcs.
    station.launch_delegate(
        "thumbnail_watcher", **thumbnail_watch_launch_spec, **delkwargs
    )
    # thumbnail-making delegate
    station.launch_delegate("browsemaker", **browse_launch_spec, **delkwargs)
    # delegate configuration
    station.set_delegate_properties(
        "image_watcher",
        image_watch_mock=mock,
        image_watch_parameters=[p for p in PARAMETERS if "Images" in p],
        image_watch_processor_path=processor_path,
        image_watch_url=yamcs_url,
    )
    station.set_delegate_properties(
        "light_watcher",
        light_watch_mock=mock,
        light_watch_parameters=[p for p in PARAMETERS if "Light" in p],
        light_watch_processor_path=processor_path,
        light_watch_url=yamcs_url,
        # the light watcher manages its own on-disk backup event log,
        # analogous to the json labels produced in create_image.create()
        light_watch_logpath=LIGHTSTATE_LOG_FILE,
    )
    station.set_delegate_properties(
        "image_processor", image_processor_outdir=DATA_ROOT
    )
    #
    station.set_delegate_properties(
        "thumbnail_watcher", **thumbnail_watch_config_spec
    )
    # note that there are no special properties to set for the thumbnail maker.
    # it uses a generic FuncCaller Actor and gets all the details from
    # Instructions.
